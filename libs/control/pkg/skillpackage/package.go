package skillpackage

import (
	"archive/zip"
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"path"
	"sort"
	"strings"
	"unicode/utf8"

	"agentctl/pkg/domain"

	"gopkg.in/yaml.v3"
)

const (
	defaultMaxArchiveBytes int64 = 16 << 20
	defaultMaxFileBytes    int64 = 4 << 20
	defaultMaxFileCount          = 512
)

// Limits constrains one uploaded skill archive.
type Limits struct {
	MaxArchiveBytes int64
	MaxFileBytes    int64
	MaxFileCount    int
}

// ParseOptions controls how one skill archive is validated.
type ParseOptions struct {
	ExpectedName string
	Status       domain.AuthoredStatus
	Limits       Limits
}

// Frontmatter is the normalized subset exposed by northbound skill APIs.
type Frontmatter struct {
	Name          string
	Description   string
	License       any
	Compatibility any
	Metadata      any
	AllowedTools  any
	Raw           map[string]any
}

// FileManifestEntry describes one file inside the skill snapshot.
type FileManifestEntry struct {
	Path   string
	Size   int64
	SHA256 string
}

// Snapshot is the parsed control-plane snapshot derived from one uploaded zip.
type Snapshot struct {
	Skill       domain.Skill
	Frontmatter Frontmatter
}

// Description is the derived northbound read model for one stored skill snapshot.
type Description struct {
	Frontmatter    Frontmatter
	Manifest       []FileManifestEntry
	SnapshotDigest string
	FileCount      int
	ParseError     string
}

type archiveEntry struct {
	Path    string
	Content string
}

// ParseZip parses one uploaded skill zip into the canonical control-plane snapshot.
func ParseZip(data []byte, options ParseOptions) (Snapshot, error) {
	limits := options.Limits.withDefaults()
	if int64(len(data)) > limits.MaxArchiveBytes {
		return Snapshot{}, fmt.Errorf("skill package exceeds max archive size %d bytes", limits.MaxArchiveBytes)
	}

	reader, err := zip.NewReader(bytes.NewReader(data), int64(len(data)))
	if err != nil {
		return Snapshot{}, fmt.Errorf("open skill package zip: %w", err)
	}

	entries, err := readArchiveEntries(reader.File, limits)
	if err != nil {
		return Snapshot{}, err
	}
	rootPrefix, err := detectRootPrefix(entries)
	if err != nil {
		return Snapshot{}, err
	}

	filesByPath := make(map[string]string, len(entries))
	for _, entry := range entries {
		relativePath := strings.TrimPrefix(entry.Path, rootPrefix)
		normalizedPath, err := normalizeSnapshotPath(relativePath, false)
		if err != nil {
			return Snapshot{}, err
		}
		if _, exists := filesByPath[normalizedPath]; exists {
			return Snapshot{}, fmt.Errorf("skill package contains duplicate path %q", normalizedPath)
		}
		filesByPath[normalizedPath] = entry.Content
	}

	skillMD, ok := filesByPath["SKILL.md"]
	if !ok {
		return Snapshot{}, errors.New("skill package must contain SKILL.md")
	}

	frontmatter, err := ParseSkillContent(skillMD)
	if err != nil {
		return Snapshot{}, err
	}
	if rootPrefix != "" {
		wrapperDir := strings.TrimSuffix(rootPrefix, "/")
		if wrapperDir != frontmatter.Name {
			return Snapshot{}, fmt.Errorf(
				"skill package wrapper directory %q must match frontmatter name %q",
				wrapperDir,
				frontmatter.Name,
			)
		}
	}
	if expectedName := strings.TrimSpace(options.ExpectedName); expectedName != "" && expectedName != frontmatter.Name {
		return Snapshot{}, fmt.Errorf(
			"skill package frontmatter name %q must match target skill %q",
			frontmatter.Name,
			expectedName,
		)
	}

	paths := make([]string, 0, len(filesByPath))
	for filePath := range filesByPath {
		if filePath == "SKILL.md" {
			continue
		}
		paths = append(paths, filePath)
	}
	sort.Strings(paths)

	files := make([]domain.SkillFile, 0, len(paths))
	for _, filePath := range paths {
		files = append(files, domain.SkillFile{
			Path:    filePath,
			Content: filesByPath[filePath],
		})
	}

	status := options.Status
	if status == "" {
		status = domain.AuthoredStatusPublished
	}

	return Snapshot{
		Skill: domain.Skill{
			Name:        frontmatter.Name,
			Description: frontmatter.Description,
			Content:     skillMD,
			Files:       files,
			Status:      status,
		},
		Frontmatter: frontmatter,
	}, nil
}

// ParseSkillContent parses one stored `SKILL.md` document.
func ParseSkillContent(content string) (Frontmatter, error) {
	document := strings.TrimPrefix(content, "\ufeff")
	yamlText, err := extractFrontmatter(document)
	if err != nil {
		return Frontmatter{}, err
	}

	raw := make(map[string]any)
	if err := yaml.Unmarshal([]byte(yamlText), &raw); err != nil {
		return Frontmatter{}, fmt.Errorf("parse SKILL.md frontmatter: %w", err)
	}

	name, ok := raw["name"].(string)
	if !ok || strings.TrimSpace(name) == "" {
		return Frontmatter{}, errors.New("skill frontmatter field \"name\" must be a non-empty string")
	}
	description, ok := raw["description"].(string)
	if !ok || strings.TrimSpace(description) == "" {
		return Frontmatter{}, errors.New("skill frontmatter field \"description\" must be a non-empty string")
	}

	return Frontmatter{
		Name:          strings.TrimSpace(name),
		Description:   strings.TrimSpace(description),
		License:       raw["license"],
		Compatibility: raw["compatibility"],
		Metadata:      raw["metadata"],
		AllowedTools:  raw["allowed-tools"],
		Raw:           raw,
	}, nil
}

// Describe derives summary/detail metadata from one stored skill snapshot.
func Describe(skill domain.Skill) Description {
	manifest := buildManifest(skill)
	description := Description{
		Manifest:       manifest,
		SnapshotDigest: computeSnapshotDigest(manifest),
		FileCount:      len(manifest),
	}

	frontmatter, err := ParseSkillContent(skill.Content)
	if err != nil {
		description.Frontmatter = Frontmatter{
			Name:        skill.Name,
			Description: skill.Description,
		}
		description.ParseError = err.Error()
		return description
	}

	description.Frontmatter = frontmatter
	return description
}

// BuildZip exports one stored skill snapshot as a deterministic zip archive.
func BuildZip(skill domain.Skill) ([]byte, error) {
	skillName := strings.TrimSpace(skill.Name)
	if skillName == "" {
		return nil, errors.New("skill name must not be empty")
	}

	var buffer bytes.Buffer
	writer := zip.NewWriter(&buffer)

	if err := writeZipFile(writer, skillName+"/SKILL.md", skill.Content); err != nil {
		return nil, err
	}

	files := append([]domain.SkillFile(nil), skill.Files...)
	sort.Slice(files, func(i int, j int) bool {
		return files[i].Path < files[j].Path
	})
	for _, file := range files {
		normalizedPath, err := normalizeSnapshotPath(file.Path, true)
		if err != nil {
			return nil, err
		}
		if err := writeZipFile(writer, skillName+"/"+normalizedPath, file.Content); err != nil {
			return nil, err
		}
	}

	if err := writer.Close(); err != nil {
		return nil, fmt.Errorf("close skill package zip: %w", err)
	}
	return buffer.Bytes(), nil
}

func (limits Limits) withDefaults() Limits {
	if limits.MaxArchiveBytes <= 0 {
		limits.MaxArchiveBytes = defaultMaxArchiveBytes
	}
	if limits.MaxFileBytes <= 0 {
		limits.MaxFileBytes = defaultMaxFileBytes
	}
	if limits.MaxFileCount <= 0 {
		limits.MaxFileCount = defaultMaxFileCount
	}
	return limits
}

func readArchiveEntries(files []*zip.File, limits Limits) ([]archiveEntry, error) {
	entries := make([]archiveEntry, 0, len(files))
	seen := make(map[string]struct{}, len(files))
	totalSize := int64(0)

	for _, file := range files {
		if file.FileInfo().IsDir() {
			continue
		}
		if file.UncompressedSize64 > uint64(limits.MaxFileBytes) {
			return nil, fmt.Errorf("skill package file %q exceeds max file size %d bytes", file.Name, limits.MaxFileBytes)
		}

		normalizedPath, err := normalizeArchiveEntryPath(file.Name)
		if err != nil {
			return nil, err
		}
		if shouldIgnorePath(normalizedPath) {
			continue
		}

		if _, exists := seen[normalizedPath]; exists {
			return nil, fmt.Errorf("skill package contains duplicate path %q", normalizedPath)
		}
		seen[normalizedPath] = struct{}{}

		reader, err := file.Open()
		if err != nil {
			return nil, fmt.Errorf("open skill package file %q: %w", file.Name, err)
		}
		contentBytes, readErr := io.ReadAll(io.LimitReader(reader, limits.MaxFileBytes+1))
		closeErr := reader.Close()
		if readErr != nil {
			return nil, fmt.Errorf("read skill package file %q: %w", file.Name, readErr)
		}
		if closeErr != nil {
			return nil, fmt.Errorf("close skill package file %q: %w", file.Name, closeErr)
		}
		if int64(len(contentBytes)) > limits.MaxFileBytes {
			return nil, fmt.Errorf("skill package file %q exceeds max file size %d bytes", file.Name, limits.MaxFileBytes)
		}
		if !utf8.Valid(contentBytes) {
			return nil, fmt.Errorf("skill package file %q is not valid UTF-8 text", file.Name)
		}

		totalSize += int64(len(contentBytes))
		if totalSize > limits.MaxArchiveBytes {
			return nil, fmt.Errorf("skill package exceeds max archive size %d bytes", limits.MaxArchiveBytes)
		}

		entries = append(entries, archiveEntry{
			Path:    normalizedPath,
			Content: string(contentBytes),
		})
		if len(entries) > limits.MaxFileCount {
			return nil, fmt.Errorf("skill package exceeds max file count %d", limits.MaxFileCount)
		}
	}

	if len(entries) == 0 {
		return nil, errors.New("skill package does not contain any files")
	}
	return entries, nil
}

func detectRootPrefix(entries []archiveEntry) (string, error) {
	directSkillCount := 0
	nestedSkillPaths := make([]string, 0, 1)
	for _, entry := range entries {
		switch {
		case entry.Path == "SKILL.md":
			directSkillCount++
		case path.Base(entry.Path) == "SKILL.md":
			nestedSkillPaths = append(nestedSkillPaths, entry.Path)
		}
	}

	switch {
	case directSkillCount == 1 && len(nestedSkillPaths) == 0:
		return "", nil
	case directSkillCount > 1 || (directSkillCount == 1 && len(nestedSkillPaths) > 0):
		return "", errors.New("skill package must contain exactly one SKILL.md")
	case len(nestedSkillPaths) != 1:
		return "", errors.New("skill package must contain exactly one SKILL.md")
	}

	wrappedSkillPath := nestedSkillPaths[0]
	rootDir := strings.TrimSuffix(wrappedSkillPath, "/SKILL.md")
	if rootDir == "" || strings.Contains(rootDir, "/") {
		return "", errors.New("skill package SKILL.md must be at archive root or under a single wrapper directory")
	}
	rootPrefix := rootDir + "/"
	for _, entry := range entries {
		if !strings.HasPrefix(entry.Path, rootPrefix) {
			return "", errors.New("skill package must contain exactly one skill root directory")
		}
	}
	return rootPrefix, nil
}

func extractFrontmatter(content string) (string, error) {
	normalized := strings.ReplaceAll(content, "\r\n", "\n")
	lines := strings.Split(normalized, "\n")
	if len(lines) == 0 || strings.TrimSpace(lines[0]) != "---" {
		return "", errors.New("SKILL.md must start with YAML frontmatter")
	}

	for index := 1; index < len(lines); index++ {
		if strings.TrimSpace(lines[index]) == "---" {
			return strings.Join(lines[1:index], "\n"), nil
		}
	}
	return "", errors.New("SKILL.md frontmatter is not closed")
}

func buildManifest(skill domain.Skill) []FileManifestEntry {
	entries := make([]FileManifestEntry, 0, len(skill.Files)+1)
	entries = append(entries, newManifestEntry("SKILL.md", skill.Content))

	files := append([]domain.SkillFile(nil), skill.Files...)
	sort.Slice(files, func(i int, j int) bool {
		return files[i].Path < files[j].Path
	})
	for _, file := range files {
		normalizedPath, err := normalizeSnapshotPath(file.Path, true)
		if err != nil {
			normalizedPath = strings.TrimSpace(file.Path)
			if normalizedPath == "" {
				normalizedPath = "invalid-path"
			}
		}
		entries = append(entries, newManifestEntry(normalizedPath, file.Content))
	}
	return entries
}

func newManifestEntry(filePath string, content string) FileManifestEntry {
	digest := sha256.Sum256([]byte(content))
	return FileManifestEntry{
		Path:   filePath,
		Size:   int64(len([]byte(content))),
		SHA256: hex.EncodeToString(digest[:]),
	}
}

func computeSnapshotDigest(manifest []FileManifestEntry) string {
	hash := sha256.New()
	for _, entry := range manifest {
		_, _ = hash.Write([]byte(entry.Path))
		_, _ = hash.Write([]byte{0})
		_, _ = hash.Write([]byte(entry.SHA256))
		_, _ = hash.Write([]byte{0})
	}
	return hex.EncodeToString(hash.Sum(nil))
}

func writeZipFile(writer *zip.Writer, filePath string, content string) error {
	header := &zip.FileHeader{
		Name:   filePath,
		Method: zip.Deflate,
	}
	entryWriter, err := writer.CreateHeader(header)
	if err != nil {
		return fmt.Errorf("create skill package file %q: %w", filePath, err)
	}
	if _, err := io.Copy(entryWriter, strings.NewReader(content)); err != nil {
		return fmt.Errorf("write skill package file %q: %w", filePath, err)
	}
	return nil
}

func normalizeArchiveEntryPath(raw string) (string, error) {
	trimmed := strings.TrimSpace(raw)
	if trimmed == "" {
		return "", errors.New("skill package contains an empty file path")
	}
	if strings.HasPrefix(trimmed, "/") || strings.HasPrefix(trimmed, "\\") {
		return "", fmt.Errorf("skill package file path must be relative: %s", raw)
	}
	if len(trimmed) >= 2 && trimmed[1] == ':' {
		return "", fmt.Errorf("skill package file path must be relative: %s", raw)
	}

	normalized := strings.ReplaceAll(trimmed, "\\", "/")
	cleaned := path.Clean(normalized)
	switch {
	case cleaned == ".":
		return "", fmt.Errorf("skill package file path must point to a file: %s", raw)
	case cleaned == "..":
		return "", fmt.Errorf("skill package file path escapes skill directory: %s", raw)
	case strings.HasPrefix(cleaned, "../"):
		return "", fmt.Errorf("skill package file path escapes skill directory: %s", raw)
	}
	return cleaned, nil
}

func normalizeSnapshotPath(raw string, reserveSkillMD bool) (string, error) {
	trimmed := strings.TrimSpace(raw)
	if trimmed == "" {
		return "", errors.New("skill file path cannot be empty")
	}
	if strings.HasPrefix(trimmed, "/") || strings.HasPrefix(trimmed, "\\") {
		return "", fmt.Errorf("skill file path must be relative: %s", raw)
	}
	if len(trimmed) >= 2 && trimmed[1] == ':' {
		return "", fmt.Errorf("skill file path must be relative: %s", raw)
	}
	if strings.HasSuffix(trimmed, "/") || strings.HasSuffix(trimmed, "\\") {
		return "", fmt.Errorf("skill file path must point to a file: %s", raw)
	}

	normalized := strings.ReplaceAll(trimmed, "\\", "/")
	cleaned := path.Clean(normalized)
	switch {
	case cleaned == ".":
		return "", fmt.Errorf("skill file path must point to a file: %s", raw)
	case cleaned == "..":
		return "", fmt.Errorf("skill file path escapes skill directory: %s", raw)
	case strings.HasPrefix(cleaned, "../"):
		return "", fmt.Errorf("skill file path escapes skill directory: %s", raw)
	case reserveSkillMD && cleaned == "SKILL.md":
		return "", errors.New("skill file path 'SKILL.md' is reserved")
	}
	return cleaned, nil
}

func shouldIgnorePath(filePath string) bool {
	for _, segment := range strings.Split(filePath, "/") {
		switch segment {
		case ".git", ".idea", ".venv", "__pycache__", ".DS_Store":
			return true
		}
	}
	return strings.HasSuffix(filePath, ".pyc")
}
