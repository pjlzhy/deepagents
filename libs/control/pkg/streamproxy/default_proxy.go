package streamproxy

import (
	"agentctl/pkg/runtimeclient"
	"context"
	"errors"
	"fmt"
	"time"
)

var (
	ErrNilUpstream   = errors.New("upstream run stream must not be nil")
	ErrNilDownstream = errors.New("downstream must not be nil")
)

// DecisionEnvelope 表示一条待转发到 southbound 的 HITL decision。
type DecisionEnvelope struct {
	InterruptID string
	Decisions   []runtimeclient.ToolDecision
}

// DecisionSource 表示能够从 northbound 提供 HITL decision 的消费者。
type DecisionSource interface {
	HITLDecisions() <-chan DecisionEnvelope
}

// CancelSignal 表示一条待转发到 southbound 的取消请求。
type CancelSignal struct {
	Reason string
}

// CancelSource 表示能够从 northbound 提供取消信号的消费者。
type CancelSource interface {
	CancelRequests() <-chan CancelSignal
}

// RunAuditStatus 表示一次 run proxy 的最终观测结果。
type RunAuditStatus string

const (
	RunAuditStatusCompleted   RunAuditStatus = "completed"
	RunAuditStatusCanceled    RunAuditStatus = "canceled"
	RunAuditStatusFailed      RunAuditStatus = "failed"
	RunAuditStatusInterrupted RunAuditStatus = "interrupted"
)

// RunAudit 记录一次 northbound <-> southbound run proxy 的最终摘要。
type RunAudit struct {
	RunID        string
	AgentName    string
	ThreadID     string
	Status       RunAuditStatus
	Reason       string
	ErrorMessage string
	StartedAt    time.Time
	FinishedAt   time.Time
}

// AuditSink 接收 run proxy 的审计结果。
type AuditSink interface {
	RecordRun(ctx context.Context, audit RunAudit) error
}

// DefaultProxy 提供默认的 run stream 代理实现。
type DefaultProxy struct {
	auditSink AuditSink
}

// NewDefaultProxy 创建一个默认代理。
func NewDefaultProxy(auditSink AuditSink) *DefaultProxy {
	return &DefaultProxy{auditSink: auditSink}
}

// Proxy 转发 southbound 事件，并按需转发 northbound 的 HITL/cancel 控制消息。
func (p *DefaultProxy) Proxy(
	ctx context.Context,
	upstream runtimeclient.RunStream,
	downstream Downstream,
) (err error) {
	switch {
	case upstream == nil:
		return ErrNilUpstream
	case downstream == nil:
		return ErrNilDownstream
	}

	childCtx, cancel := context.WithCancel(ctx)
	tracker := runAuditTracker{}
	defer func() {
		cancel()
		err = errors.Join(err, p.recordAudit(childCtx, tracker.finalize(err)))
		err = errors.Join(err, upstream.Close())
	}()

	controlErrs := make(chan error, 2)
	p.startDecisionForwarder(childCtx, upstream, downstream, controlErrs)
	p.startCancelForwarder(childCtx, upstream, downstream, controlErrs)

	events := upstream.Events()
	for {
		select {
		case <-childCtx.Done():
			return childCtx.Err()
		case err := <-controlErrs:
			if err != nil {
				return err
			}
		case event, ok := <-events:
			if !ok {
				return nil
			}

			tracker.observe(event)
			if err := downstream.SendEvent(childCtx, event); err != nil {
				return fmt.Errorf("forward event %q: %w", event.Type, err)
			}
		}
	}
}

func (p *DefaultProxy) startDecisionForwarder(
	ctx context.Context,
	upstream runtimeclient.RunStream,
	downstream Downstream,
	errs chan<- error,
) {
	source, ok := downstream.(DecisionSource)
	if !ok {
		return
	}

	decisions := source.HITLDecisions()
	if decisions == nil {
		return
	}

	go func() {
		for {
			select {
			case <-ctx.Done():
				return
			case envelope, ok := <-decisions:
				if !ok {
					return
				}
				if err := upstream.SendHITLDecision(ctx, envelope.InterruptID, envelope.Decisions); err != nil {
					sendProxyError(errs, fmt.Errorf("forward HITL decision %q: %w", envelope.InterruptID, err))
					return
				}
			}
		}
	}()
}

func (p *DefaultProxy) startCancelForwarder(
	ctx context.Context,
	upstream runtimeclient.RunStream,
	downstream Downstream,
	errs chan<- error,
) {
	source, ok := downstream.(CancelSource)
	if !ok {
		return
	}

	cancels := source.CancelRequests()
	if cancels == nil {
		return
	}

	go func() {
		for {
			select {
			case <-ctx.Done():
				return
			case signal, ok := <-cancels:
				if !ok {
					return
				}
				if err := upstream.SendCancel(ctx, signal.Reason); err != nil {
					sendProxyError(errs, fmt.Errorf("forward cancel request: %w", err))
					return
				}
			}
		}
	}()
}

func (p *DefaultProxy) recordAudit(ctx context.Context, audit RunAudit) error {
	if p.auditSink == nil {
		return nil
	}
	if !audit.recordable() {
		return nil
	}

	recordCtx := context.WithoutCancel(ctx)
	if err := p.auditSink.RecordRun(recordCtx, audit); err != nil {
		return fmt.Errorf("record run audit: %w", err)
	}
	return nil
}

func sendProxyError(errs chan<- error, err error) {
	select {
	case errs <- err:
	default:
	}
}

type runAuditTracker struct {
	audit       RunAudit
	terminalSet bool
}

func (t *runAuditTracker) observe(event runtimeclient.AgentEvent) {
	if t.audit.RunID == "" && event.RunID != "" {
		t.audit.RunID = event.RunID
	}
	if t.audit.AgentName == "" && event.AgentName != "" {
		t.audit.AgentName = event.AgentName
	}
	if t.audit.ThreadID == "" && event.ThreadID != "" {
		t.audit.ThreadID = event.ThreadID
	}

	timestamp := normalizeEventTime(event.Timestamp)
	if event.Type == runtimeclient.AgentEventTypeRunStarted && t.audit.StartedAt.IsZero() {
		t.audit.StartedAt = timestamp
	}

	switch event.Type {
	case runtimeclient.AgentEventTypeRunEnded:
		t.terminalSet = true
		t.audit.Status = RunAuditStatusCompleted
		t.audit.FinishedAt = timestamp
	case runtimeclient.AgentEventTypeRunCanceled:
		t.terminalSet = true
		t.audit.Status = RunAuditStatusCanceled
		t.audit.Reason = event.Reason
		t.audit.FinishedAt = timestamp
	case runtimeclient.AgentEventTypeError:
		t.terminalSet = true
		t.audit.Status = RunAuditStatusFailed
		t.audit.ErrorMessage = event.ErrorMessage
		t.audit.FinishedAt = timestamp
	}
}

func (t *runAuditTracker) finalize(runErr error) RunAudit {
	if t.audit.StartedAt.IsZero() && t.audit.FinishedAt.IsZero() && t.audit.RunID == "" &&
		t.audit.AgentName == "" && t.audit.ThreadID == "" {
		return RunAudit{}
	}

	if t.audit.StartedAt.IsZero() {
		t.audit.StartedAt = time.Now().UTC()
	}

	if t.audit.FinishedAt.IsZero() {
		t.audit.FinishedAt = time.Now().UTC()
	}

	if !t.terminalSet && runErr != nil {
		switch {
		case errors.Is(runErr, context.Canceled), errors.Is(runErr, context.DeadlineExceeded):
			t.audit.Status = RunAuditStatusInterrupted
			t.audit.Reason = runErr.Error()
		default:
			t.audit.Status = RunAuditStatusFailed
			t.audit.ErrorMessage = runErr.Error()
		}
	}

	return t.audit
}

func (a RunAudit) recordable() bool {
	return a.Status != "" || a.RunID != "" || a.AgentName != "" || a.ThreadID != ""
}

func normalizeEventTime(value time.Time) time.Time {
	if value.IsZero() {
		return time.Now().UTC()
	}
	return value.UTC()
}
