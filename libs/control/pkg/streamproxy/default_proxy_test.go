package streamproxy

import (
	"agentctl/pkg/runtimeclient"
	"context"
	"errors"
	"sync"
	"testing"
	"time"
)

type stubRunStream struct {
	events chan runtimeclient.AgentEvent

	mu              sync.Mutex
	decisions       []DecisionEnvelope
	cancels         []string
	sendDecisionErr error
	sendCancelErr   error
	closeErr        error
	closeCalls      int

	decisionSignal chan struct{}
	cancelSignal   chan struct{}
}

func newStubRunStream() *stubRunStream {
	return &stubRunStream{
		events:         make(chan runtimeclient.AgentEvent, 16),
		decisionSignal: make(chan struct{}, 1),
		cancelSignal:   make(chan struct{}, 1),
	}
}

func (s *stubRunStream) Events() <-chan runtimeclient.AgentEvent {
	return s.events
}

func (s *stubRunStream) SendHITLDecision(
	_ context.Context,
	interruptID string,
	decisions []runtimeclient.ToolDecision,
) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	s.decisions = append(s.decisions, DecisionEnvelope{
		InterruptID: interruptID,
		Decisions:   decisions,
	})
	select {
	case s.decisionSignal <- struct{}{}:
	default:
	}
	return s.sendDecisionErr
}

func (s *stubRunStream) SendCancel(_ context.Context, reason string) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	s.cancels = append(s.cancels, reason)
	select {
	case s.cancelSignal <- struct{}{}:
	default:
	}
	return s.sendCancelErr
}

func (s *stubRunStream) Close() error {
	s.mu.Lock()
	defer s.mu.Unlock()

	s.closeCalls++
	return s.closeErr
}

type stubDownstream struct {
	mu sync.Mutex

	events    []runtimeclient.AgentEvent
	sendErr   error
	failOn    runtimeclient.AgentEventType
	decisions chan DecisionEnvelope
	cancels   chan CancelSignal
}

func newStubDownstream() *stubDownstream {
	return &stubDownstream{
		decisions: make(chan DecisionEnvelope, 4),
		cancels:   make(chan CancelSignal, 4),
	}
}

func (d *stubDownstream) SendEvent(_ context.Context, event runtimeclient.AgentEvent) error {
	d.mu.Lock()
	defer d.mu.Unlock()

	if d.sendErr != nil && event.Type == d.failOn {
		return d.sendErr
	}
	d.events = append(d.events, event)
	return nil
}

func (d *stubDownstream) HITLDecisions() <-chan DecisionEnvelope {
	return d.decisions
}

func (d *stubDownstream) CancelRequests() <-chan CancelSignal {
	return d.cancels
}

type stubAuditSink struct {
	mu     sync.Mutex
	audits []RunAudit
	err    error
}

func (s *stubAuditSink) RecordRun(_ context.Context, audit RunAudit) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	s.audits = append(s.audits, audit)
	return s.err
}

func TestDefaultProxyRejectsNilEndpoints(t *testing.T) {
	proxy := NewDefaultProxy(nil)
	downstream := newStubDownstream()

	if err := proxy.Proxy(context.Background(), nil, downstream); !errors.Is(err, ErrNilUpstream) {
		t.Fatalf("expected ErrNilUpstream, got %v", err)
	}
	if err := proxy.Proxy(context.Background(), newStubRunStream(), nil); !errors.Is(err, ErrNilDownstream) {
		t.Fatalf("expected ErrNilDownstream, got %v", err)
	}
}

func TestDefaultProxyForwardsEventsAndRecordsCompletedAudit(t *testing.T) {
	upstream := newStubRunStream()
	downstream := newStubDownstream()
	auditSink := &stubAuditSink{}
	proxy := NewDefaultProxy(auditSink)

	startedAt := time.Date(2026, 3, 26, 10, 0, 0, 0, time.UTC)
	finishedAt := startedAt.Add(2 * time.Second)

	go func() {
		upstream.events <- runtimeclient.AgentEvent{
			Type:      runtimeclient.AgentEventTypeRunStarted,
			RunID:     "run-1",
			AgentName: "assistant",
			ThreadID:  "thread-1",
			Timestamp: startedAt,
		}
		upstream.events <- runtimeclient.AgentEvent{
			Type:      runtimeclient.AgentEventTypeTextDelta,
			RunID:     "run-1",
			AgentName: "assistant",
			ThreadID:  "thread-1",
			Text:      "hello",
		}
		upstream.events <- runtimeclient.AgentEvent{
			Type:      runtimeclient.AgentEventTypeRunEnded,
			RunID:     "run-1",
			AgentName: "assistant",
			ThreadID:  "thread-1",
			Timestamp: finishedAt,
		}
		close(upstream.events)
	}()

	if err := proxy.Proxy(context.Background(), upstream, downstream); err != nil {
		t.Fatalf("Proxy returned error: %v", err)
	}

	downstream.mu.Lock()
	defer downstream.mu.Unlock()
	if len(downstream.events) != 3 {
		t.Fatalf("expected 3 forwarded events, got %d", len(downstream.events))
	}
	if downstream.events[0].Type != runtimeclient.AgentEventTypeRunStarted ||
		downstream.events[2].Type != runtimeclient.AgentEventTypeRunEnded {
		t.Fatalf("unexpected event sequence: %#v", downstream.events)
	}

	auditSink.mu.Lock()
	defer auditSink.mu.Unlock()
	if len(auditSink.audits) != 1 {
		t.Fatalf("expected 1 audit record, got %d", len(auditSink.audits))
	}
	audit := auditSink.audits[0]
	if audit.Status != RunAuditStatusCompleted || audit.RunID != "run-1" ||
		audit.AgentName != "assistant" || audit.ThreadID != "thread-1" {
		t.Fatalf("unexpected audit: %#v", audit)
	}
	if !audit.StartedAt.Equal(startedAt) || !audit.FinishedAt.Equal(finishedAt) {
		t.Fatalf("unexpected audit timestamps: %#v", audit)
	}
	if upstream.closeCalls != 1 {
		t.Fatalf("expected upstream close once, got %d", upstream.closeCalls)
	}
}

func TestDefaultProxyForwardsControlMessages(t *testing.T) {
	upstream := newStubRunStream()
	downstream := newStubDownstream()
	proxy := NewDefaultProxy(nil)

	errCh := make(chan error, 1)
	go func() {
		errCh <- proxy.Proxy(context.Background(), upstream, downstream)
	}()

	downstream.decisions <- DecisionEnvelope{
		InterruptID: "interrupt-1",
		Decisions: []runtimeclient.ToolDecision{
			{Type: "approve"},
		},
	}
	downstream.cancels <- CancelSignal{Reason: "user canceled"}

	waitForSignal(t, upstream.decisionSignal, "decision")
	waitForSignal(t, upstream.cancelSignal, "cancel")

	close(downstream.decisions)
	close(downstream.cancels)
	close(upstream.events)

	if err := <-errCh; err != nil {
		t.Fatalf("Proxy returned error: %v", err)
	}

	upstream.mu.Lock()
	defer upstream.mu.Unlock()
	if len(upstream.decisions) != 1 || upstream.decisions[0].InterruptID != "interrupt-1" {
		t.Fatalf("unexpected forwarded decisions: %#v", upstream.decisions)
	}
	if len(upstream.cancels) != 1 || upstream.cancels[0] != "user canceled" {
		t.Fatalf("unexpected forwarded cancels: %#v", upstream.cancels)
	}
}

func TestDefaultProxyReturnsEventForwardErrorAndRecordsFailureAudit(t *testing.T) {
	upstream := newStubRunStream()
	downstream := newStubDownstream()
	downstream.sendErr = errors.New("downstream write failed")
	downstream.failOn = runtimeclient.AgentEventTypeTextDelta
	auditSink := &stubAuditSink{}
	proxy := NewDefaultProxy(auditSink)

	go func() {
		upstream.events <- runtimeclient.AgentEvent{
			Type:      runtimeclient.AgentEventTypeRunStarted,
			RunID:     "run-2",
			AgentName: "assistant",
			ThreadID:  "thread-2",
		}
		upstream.events <- runtimeclient.AgentEvent{
			Type:      runtimeclient.AgentEventTypeTextDelta,
			RunID:     "run-2",
			AgentName: "assistant",
			ThreadID:  "thread-2",
			Text:      "boom",
		}
	}()

	err := proxy.Proxy(context.Background(), upstream, downstream)
	if err == nil || !errors.Is(err, downstream.sendErr) {
		t.Fatalf("expected downstream send error, got %v", err)
	}

	auditSink.mu.Lock()
	defer auditSink.mu.Unlock()
	if len(auditSink.audits) != 1 {
		t.Fatalf("expected 1 audit record, got %d", len(auditSink.audits))
	}
	audit := auditSink.audits[0]
	if audit.Status != RunAuditStatusFailed || audit.RunID != "run-2" {
		t.Fatalf("unexpected audit: %#v", audit)
	}
	if audit.ErrorMessage == "" {
		t.Fatalf("expected failure audit message, got %#v", audit)
	}
}

func TestDefaultProxyReturnsControlForwardError(t *testing.T) {
	upstream := newStubRunStream()
	upstream.sendCancelErr = errors.New("cancel failed")
	downstream := newStubDownstream()
	proxy := NewDefaultProxy(nil)

	errCh := make(chan error, 1)
	go func() {
		errCh <- proxy.Proxy(context.Background(), upstream, downstream)
	}()

	downstream.cancels <- CancelSignal{Reason: "user canceled"}

	err := waitForProxyError(t, errCh)
	if !errors.Is(err, upstream.sendCancelErr) {
		t.Fatalf("expected cancel forwarding error, got %v", err)
	}
}

func waitForSignal(t *testing.T, signal <-chan struct{}, name string) {
	t.Helper()

	select {
	case <-signal:
	case <-time.After(2 * time.Second):
		t.Fatalf("timed out waiting for %s signal", name)
	}
}

func waitForProxyError(t *testing.T, errCh <-chan error) error {
	t.Helper()

	select {
	case err := <-errCh:
		return err
	case <-time.After(2 * time.Second):
		t.Fatal("timed out waiting for proxy result")
		return nil
	}
}
