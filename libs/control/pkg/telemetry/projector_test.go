package telemetry

import (
	"encoding/json"
	"testing"
	"time"

	"agentctl/pkg/domain"
)

func TestBuildStepsProjectsNodeModelToolAndHitlSteps(t *testing.T) {
	events := []domain.TelemetryEventRecord{
		{
			EventID:    "run-1:1:1",
			RunID:      "run-1",
			AgentName:  "assistant",
			Attempt:    1,
			Seq:        1,
			Timestamp:  time.Unix(1710000000, 0).UTC(),
			StreamMode: "lifecycle",
			EventType:  "run_started",
			NodeName:   "run",
		},
		{
			EventID:    "run-1:1:2",
			RunID:      "run-1",
			AgentName:  "assistant",
			Attempt:    1,
			Seq:        2,
			Timestamp:  time.Unix(1710000001, 0).UTC(),
			Namespace:  []string{"task:research"},
			StreamMode: "debug",
			EventType:  "task",
			NodeName:   "research",
			TaskID:     "task-1",
			Metadata:   json.RawMessage(`{"step":2}`),
			Payload:    json.RawMessage(`{"id":"task-1","name":"research","input":{"question":"why"}}`),
		},
		{
			EventID:     "run-1:1:3",
			RunID:       "run-1",
			AgentName:   "assistant",
			Attempt:     1,
			Seq:         3,
			Timestamp:   time.Unix(1710000002, 0).UTC(),
			Namespace:   []string{"task:research"},
			StreamMode:  "messages",
			EventType:   "reasoning",
			NodeName:    "planner",
			ModelCallID: "msg-1",
			MessageID:   "msg-1",
			Payload:     json.RawMessage(`{"summary":[{"text":"thinking..."}]}`),
		},
		{
			EventID:     "run-1:1:4",
			RunID:       "run-1",
			AgentName:   "assistant",
			Attempt:     1,
			Seq:         4,
			Timestamp:   time.Unix(1710000003, 0).UTC(),
			Namespace:   []string{"task:research"},
			StreamMode:  "messages",
			EventType:   "text_done",
			NodeName:    "planner",
			ModelCallID: "msg-1",
			MessageID:   "msg-1",
			Payload:     json.RawMessage(`{"text":"done"}`),
		},
		{
			EventID:    "run-1:1:5",
			RunID:      "run-1",
			AgentName:  "assistant",
			Attempt:    1,
			Seq:        5,
			Timestamp:  time.Unix(1710000004, 0).UTC(),
			Namespace:  []string{"task:research"},
			StreamMode: "messages",
			EventType:  "tool_call_start",
			NodeName:   "research",
			ToolCallID: "tool-1",
			Payload:    json.RawMessage(`{"tool_name":"search","tool_call_id":"tool-1"}`),
		},
		{
			EventID:    "run-1:1:6",
			RunID:      "run-1",
			AgentName:  "assistant",
			Attempt:    1,
			Seq:        6,
			Timestamp:  time.Unix(1710000005, 0).UTC(),
			Namespace:  []string{"task:research"},
			StreamMode: "messages",
			EventType:  "tool_result",
			NodeName:   "research",
			ToolCallID: "tool-1",
			Payload:    json.RawMessage(`{"tool_call_id":"tool-1","content":"ok","is_error":false}`),
		},
		{
			EventID:     "run-1:1:7",
			RunID:       "run-1",
			AgentName:   "assistant",
			Attempt:     1,
			Seq:         7,
			Timestamp:   time.Unix(1710000006, 0).UTC(),
			Namespace:   []string{"task:research"},
			StreamMode:  "updates",
			EventType:   "interrupt",
			NodeName:    "research",
			InterruptID: "interrupt-1",
			Payload:     json.RawMessage(`{"interrupt_id":"interrupt-1"}`),
		},
		{
			EventID:    "run-1:1:8",
			RunID:      "run-1",
			AgentName:  "assistant",
			Attempt:    1,
			Seq:        8,
			Timestamp:  time.Unix(1710000007, 0).UTC(),
			Namespace:  []string{"task:research"},
			StreamMode: "debug",
			EventType:  "task_result",
			NodeName:   "research",
			TaskID:     "task-1",
			Payload:    json.RawMessage(`{"id":"task-1","result":{"answer":"ok"}}`),
		},
		{
			EventID:    "run-1:1:9",
			RunID:      "run-1",
			AgentName:  "assistant",
			Attempt:    1,
			Seq:        9,
			Timestamp:  time.Unix(1710000008, 0).UTC(),
			StreamMode: "lifecycle",
			EventType:  "run_ended",
			NodeName:   "run",
		},
	}

	steps := BuildSteps(events)
	if len(steps) < 5 {
		t.Fatalf("expected at least 5 steps, got %d", len(steps))
	}

	index := map[string]domain.TelemetryStep{}
	for _, step := range steps {
		index[step.StepID] = step
	}

	run := index["step:run:run-1"]
	if run.Kind != domain.TelemetryStepKindRun || run.Status != domain.TelemetryStepStatusCompleted {
		t.Fatalf("unexpected run step: %#v", run)
	}

	node := index["step:node:task-1"]
	if node.Kind != domain.TelemetryStepKindNode || node.Status != domain.TelemetryStepStatusCompleted {
		t.Fatalf("unexpected node step: %#v", node)
	}
	if node.ParentStepID != "step:run:run-1" {
		t.Fatalf("unexpected node parent: %#v", node)
	}
	if len(node.Reasoning) != 1 || node.Messages[len(node.Messages)-1] != "done" {
		t.Fatalf("expected node step to inherit model summaries, got %#v", node)
	}

	model := index["step:model:msg-1"]
	if model.Kind != domain.TelemetryStepKindModel || model.Status != domain.TelemetryStepStatusCompleted {
		t.Fatalf("unexpected model step: %#v", model)
	}
	if len(model.Reasoning) != 1 || model.Messages[len(model.Messages)-1] != "done" {
		t.Fatalf("unexpected model content: %#v", model)
	}

	tool := index["step:tool:tool-1"]
	if tool.Kind != domain.TelemetryStepKindTool || tool.Status != domain.TelemetryStepStatusCompleted {
		t.Fatalf("unexpected tool step: %#v", tool)
	}

	hitl := index["step:hitl:interrupt-1"]
	if hitl.Kind != domain.TelemetryStepKindHITL {
		t.Fatalf("unexpected hitl step: %#v", hitl)
	}
}
