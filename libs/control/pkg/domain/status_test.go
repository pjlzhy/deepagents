package domain

import "testing"

func TestAuthoredStatusValid(t *testing.T) {
	if !AuthoredStatusDraft.Valid() {
		t.Fatal("expected draft to be valid")
	}
	if AuthoredStatus("unknown").Valid() {
		t.Fatal("expected unknown authored status to be invalid")
	}
}

func TestDesiredDeploymentStateValid(t *testing.T) {
	if !DesiredDeploymentStateCompiled.Valid() {
		t.Fatal("expected compiled desired state to be valid")
	}
	if DesiredDeploymentState("invalid").Valid() {
		t.Fatal("expected invalid desired state to be rejected")
	}
}

func TestObservedRuntimeStateValid(t *testing.T) {
	if !ObservedRuntimeStateRunning.Valid() {
		t.Fatal("expected running observed state to be valid")
	}
	if ObservedRuntimeState("stopped").Valid() {
		t.Fatal("expected unknown observed state to be invalid")
	}
}
