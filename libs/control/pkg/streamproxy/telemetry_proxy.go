package streamproxy

import (
	"agentctl/pkg/runtimeclient"
	"context"
	"errors"
	"fmt"
)

var (
	ErrNilTelemetryUpstream   = errors.New("upstream telemetry stream must not be nil")
	ErrNilTelemetryDownstream = errors.New("telemetry downstream must not be nil")
)

// TelemetryDownstream represents a northbound telemetry consumer.
type TelemetryDownstream interface {
	SendTelemetryEvent(ctx context.Context, event runtimeclient.TelemetryEvent) error
}

// TelemetryProxy forwards southbound telemetry events to a telemetry downstream.
type TelemetryProxy interface {
	ProxyTelemetry(ctx context.Context, upstream runtimeclient.TelemetryStream, downstream TelemetryDownstream) error
}

// DefaultTelemetryProxy provides the default telemetry stream proxy.
type DefaultTelemetryProxy struct{}

// NewDefaultTelemetryProxy constructs a telemetry proxy with default behavior.
func NewDefaultTelemetryProxy() *DefaultTelemetryProxy {
	return &DefaultTelemetryProxy{}
}

// ProxyTelemetry forwards telemetry events and northbound control messages.
func (p *DefaultTelemetryProxy) ProxyTelemetry(
	ctx context.Context,
	upstream runtimeclient.TelemetryStream,
	downstream TelemetryDownstream,
) error {
	switch {
	case upstream == nil:
		return ErrNilTelemetryUpstream
	case downstream == nil:
		return ErrNilTelemetryDownstream
	}

	childCtx, cancel := context.WithCancel(ctx)
	defer func() {
		cancel()
		_ = upstream.Close()
	}()

	controlErrs := make(chan error, 2)
	startTelemetryDecisionForwarder(childCtx, upstream, downstream, controlErrs)
	startTelemetryCancelForwarder(childCtx, upstream, downstream, controlErrs)

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

			if err := downstream.SendTelemetryEvent(childCtx, event); err != nil {
				return fmt.Errorf("forward telemetry event %q: %w", event.EventType, err)
			}
		}
	}
}

func startTelemetryDecisionForwarder(
	ctx context.Context,
	upstream runtimeclient.TelemetryStream,
	downstream TelemetryDownstream,
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
					sendProxyError(errs, fmt.Errorf("forward telemetry HITL decision %q: %w", envelope.InterruptID, err))
					return
				}
			}
		}
	}()
}

func startTelemetryCancelForwarder(
	ctx context.Context,
	upstream runtimeclient.TelemetryStream,
	downstream TelemetryDownstream,
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
					sendProxyError(errs, fmt.Errorf("forward telemetry cancel request: %w", err))
					return
				}
			}
		}
	}()
}
