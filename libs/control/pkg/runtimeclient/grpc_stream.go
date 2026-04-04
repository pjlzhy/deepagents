package runtimeclient

import (
	"context"
	"io"
	"sync"

	runtimev1 "agentctl/pkg/proto"
)

type grpcRunStream struct {
	stream    runtimev1.AgentExecutor_RunClient
	events    chan AgentEvent
	sendMu    sync.Mutex
	closeErr  error
	closeOnce sync.Once
}

type grpcTelemetryStream struct {
	stream    runtimev1.AgentTelemetry_RunTelemetryClient
	events    chan TelemetryEvent
	sendMu    sync.Mutex
	closeErr  error
	closeOnce sync.Once
}

func newGRPCRunStream(stream runtimev1.AgentExecutor_RunClient) *grpcRunStream {
	runStream := &grpcRunStream{
		stream: stream,
		events: make(chan AgentEvent, 16),
	}
	go runStream.recvLoop()
	return runStream
}

func newGRPCTelemetryStream(
	stream runtimev1.AgentTelemetry_RunTelemetryClient,
) *grpcTelemetryStream {
	telemetryStream := &grpcTelemetryStream{
		stream: stream,
		events: make(chan TelemetryEvent, 16),
	}
	go telemetryStream.recvLoop()
	return telemetryStream
}

func (s *grpcRunStream) Events() <-chan AgentEvent {
	return s.events
}

func (s *grpcTelemetryStream) Events() <-chan TelemetryEvent {
	return s.events
}

func (s *grpcRunStream) SendHITLDecision(
	ctx context.Context,
	interruptID string,
	decisions []ToolDecision,
) error {
	return s.send(ctx, &runtimev1.ClientMessage{
		Payload: &runtimev1.ClientMessage_HitlDecision{
			HitlDecision: &runtimev1.HITLDecision{
				InterruptId: interruptID,
				Decisions:   toolDecisionsToProto(decisions),
			},
		},
	})
}

func (s *grpcTelemetryStream) SendHITLDecision(
	ctx context.Context,
	interruptID string,
	decisions []ToolDecision,
) error {
	return s.send(ctx, &runtimev1.ClientMessage{
		Payload: &runtimev1.ClientMessage_HitlDecision{
			HitlDecision: &runtimev1.HITLDecision{
				InterruptId: interruptID,
				Decisions:   toolDecisionsToProto(decisions),
			},
		},
	})
}

func (s *grpcRunStream) SendCancel(ctx context.Context, reason string) error {
	return s.send(ctx, &runtimev1.ClientMessage{
		Payload: &runtimev1.ClientMessage_Cancel{
			Cancel: &runtimev1.CancelRequest{
				Reason: reason,
			},
		},
	})
}

func (s *grpcTelemetryStream) SendCancel(ctx context.Context, reason string) error {
	return s.send(ctx, &runtimev1.ClientMessage{
		Payload: &runtimev1.ClientMessage_Cancel{
			Cancel: &runtimev1.CancelRequest{
				Reason: reason,
			},
		},
	})
}

func (s *grpcRunStream) Close() error {
	s.closeOnce.Do(func() {
		s.closeErr = s.stream.CloseSend()
	})
	return s.closeErr
}

func (s *grpcTelemetryStream) Close() error {
	s.closeOnce.Do(func() {
		s.closeErr = s.stream.CloseSend()
	})
	return s.closeErr
}

func (s *grpcRunStream) send(ctx context.Context, message *runtimev1.ClientMessage) error {
	if err := ctx.Err(); err != nil {
		return err
	}

	s.sendMu.Lock()
	defer s.sendMu.Unlock()

	return s.stream.Send(message)
}

func (s *grpcTelemetryStream) send(
	ctx context.Context,
	message *runtimev1.ClientMessage,
) error {
	if err := ctx.Err(); err != nil {
		return err
	}

	s.sendMu.Lock()
	defer s.sendMu.Unlock()

	return s.stream.Send(message)
}

func (s *grpcRunStream) recvLoop() {
	defer close(s.events)

	for {
		event, err := s.stream.Recv()
		switch {
		case err == nil:
			s.events <- agentEventFromProto(event)
		case err == io.EOF:
			return
		default:
			s.events <- AgentEvent{
				Type:         AgentEventTypeError,
				ErrorMessage: err.Error(),
			}
			return
		}
	}
}

func (s *grpcTelemetryStream) recvLoop() {
	defer close(s.events)

	for {
		event, err := s.stream.Recv()
		switch {
		case err == nil:
			s.events <- telemetryEventFromProto(event)
		case err == io.EOF:
			return
		default:
			s.events <- TelemetryEvent{
				StreamMode: "lifecycle",
				EventType:  "error",
				PublicEvent: &AgentEvent{
					Type:         AgentEventTypeError,
					ErrorMessage: err.Error(),
				},
			}
			return
		}
	}
}
