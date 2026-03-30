package skillpackage

import (
	"archive/zip"
	"bytes"
	"strings"
	"testing"

	"agentctl/pkg/domain"
)

func TestParseZipAcceptsWrappedSkillDirectory(t *testing.T) {
	archive := buildTestZip(t, map[string][]byte{
		"pcap-analyzer/SKILL.md": []byte(`---
name: pcap-analyzer
description: Analyze packet captures
license: MIT
compatibility:
  required:
    - tshark>=3.0
allowed-tools:
  - execute
---

# Skill
`),
		"__MACOSX/._pcap-analyzer":                 {0xff, 0xfe, 0xfd},
		"pcap-analyzer/._SKILL.md":                 {0xff, 0xfe, 0xfd},
		"pcap-analyzer/scripts/analyze.sh":         []byte("echo analyze\n"),
		"pcap-analyzer/.DS_Store":                  []byte("ignored"),
		"pcap-analyzer/scripts/__pycache__/x.pyc":  []byte("ignored"),
		"pcap-analyzer/scripts/lib/__pycache__/y":  []byte("ignored"),
		"pcap-analyzer/scripts/lib/helpers.py":     []byte("print('ok')\n"),
		"pcap-analyzer/scripts/lib/.DS_Store":      []byte("ignored"),
		"pcap-analyzer/scripts/lib/cache/test.pyc": []byte("ignored"),
		"pcap-analyzer/scripts/lib/cache/test.txt": []byte("kept\n"),
	})

	snapshot, err := ParseZip(archive, ParseOptions{})
	if err != nil {
		t.Fatalf("ParseZip: %v", err)
	}

	if snapshot.Skill.Name != "pcap-analyzer" {
		t.Fatalf("unexpected skill name: %q", snapshot.Skill.Name)
	}
	if snapshot.Skill.Description != "Analyze packet captures" {
		t.Fatalf("unexpected skill description: %q", snapshot.Skill.Description)
	}
	if snapshot.Skill.Status != domain.AuthoredStatusPublished {
		t.Fatalf("unexpected skill status: %q", snapshot.Skill.Status)
	}
	if len(snapshot.Skill.Files) != 3 {
		t.Fatalf("unexpected skill files: %#v", snapshot.Skill.Files)
	}
	if snapshot.Skill.Files[0].Path != "scripts/analyze.sh" ||
		snapshot.Skill.Files[1].Path != "scripts/lib/cache/test.txt" ||
		snapshot.Skill.Files[2].Path != "scripts/lib/helpers.py" {
		t.Fatalf("unexpected normalized paths: %#v", snapshot.Skill.Files)
	}
	if snapshot.Frontmatter.License != "MIT" {
		t.Fatalf("unexpected license: %#v", snapshot.Frontmatter.License)
	}
	if snapshot.Frontmatter.Raw["allowed-tools"] == nil {
		t.Fatalf("expected allowed-tools in frontmatter: %#v", snapshot.Frontmatter.Raw)
	}
}

func TestParseZipRejectsReplaceNameMismatch(t *testing.T) {
	archive := buildTestZip(t, map[string][]byte{
		"other-skill/SKILL.md": []byte(`---
name: other-skill
description: mismatch
---
`),
	})

	_, err := ParseZip(archive, ParseOptions{ExpectedName: "target-skill"})
	if err == nil || !strings.Contains(err.Error(), "must match target skill") {
		t.Fatalf("expected replace mismatch error, got %v", err)
	}
}

func TestParseZipRejectsNonUTF8File(t *testing.T) {
	archive := buildTestZip(t, map[string][]byte{
		"skill/SKILL.md": []byte(`---
name: sample
description: valid
---
`),
		"skill/scripts/blob.bin": {0xff, 0xfe, 0xfd},
	})

	_, err := ParseZip(archive, ParseOptions{})
	if err == nil || !strings.Contains(err.Error(), "not valid UTF-8") {
		t.Fatalf("expected utf-8 validation error, got %v", err)
	}
}

func TestBuildZipRoundTripsSkillSnapshot(t *testing.T) {
	skill := domain.Skill{
		Name:        "research",
		Description: "Research workflow",
		Content: `---
name: research
description: Research workflow
metadata:
  owner: control
---

# Research
`,
		Files: []domain.SkillFile{
			{Path: "scripts/run.sh", Content: "echo hi\n"},
			{Path: "references/guide.md", Content: "Use the tool.\n"},
		},
		Status: domain.AuthoredStatusDraft,
	}

	archive, err := BuildZip(skill)
	if err != nil {
		t.Fatalf("BuildZip: %v", err)
	}
	parsed, err := ParseZip(archive, ParseOptions{Status: skill.Status})
	if err != nil {
		t.Fatalf("ParseZip: %v", err)
	}

	if parsed.Skill.Name != skill.Name || parsed.Skill.Description != skill.Description {
		t.Fatalf("unexpected round-trip skill: %#v", parsed.Skill)
	}
	if parsed.Skill.Status != domain.AuthoredStatusDraft {
		t.Fatalf("unexpected round-trip status: %q", parsed.Skill.Status)
	}
	if len(parsed.Skill.Files) != len(skill.Files) {
		t.Fatalf("unexpected round-trip files: %#v", parsed.Skill.Files)
	}
}

func TestDescribeFallsBackForLegacyInvalidContent(t *testing.T) {
	description := Describe(domain.Skill{
		Name:        "legacy-skill",
		Description: "legacy description",
		Content:     "# no frontmatter",
		Files:       []domain.SkillFile{{Path: "scripts/run.sh", Content: "echo hi\n"}},
	})

	if description.Frontmatter.Name != "legacy-skill" {
		t.Fatalf("unexpected fallback frontmatter: %#v", description.Frontmatter)
	}
	if description.ParseError == "" {
		t.Fatal("expected parse error for legacy content")
	}
	if description.FileCount != 2 {
		t.Fatalf("unexpected file count: %d", description.FileCount)
	}
}

func buildTestZip(t *testing.T, files map[string][]byte) []byte {
	t.Helper()

	var buffer bytes.Buffer
	writer := zip.NewWriter(&buffer)
	for filePath, content := range files {
		entry, err := writer.Create(filePath)
		if err != nil {
			t.Fatalf("Create(%q): %v", filePath, err)
		}
		if _, err := entry.Write(content); err != nil {
			t.Fatalf("Write(%q): %v", filePath, err)
		}
	}
	if err := writer.Close(); err != nil {
		t.Fatalf("Close: %v", err)
	}
	return buffer.Bytes()
}

func TestParseSkillContentRejectsMissingFrontmatter(t *testing.T) {
	_, err := ParseSkillContent("# missing")
	if err == nil || !strings.Contains(err.Error(), "frontmatter") {
		t.Fatalf("expected frontmatter parse error, got %v", err)
	}
}
