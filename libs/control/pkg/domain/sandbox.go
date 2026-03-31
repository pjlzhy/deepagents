package domain

import (
	"fmt"
	"strings"
)

// SandboxBackendKind identifies one concrete runtime sandbox backend.
type SandboxBackendKind string

const (
	SandboxBackendKindLocal      SandboxBackendKind = "local"
	SandboxBackendKindDocker     SandboxBackendKind = "docker"
	SandboxBackendKindKubernetes SandboxBackendKind = "kubernetes"
)

const DefaultSandboxImage = "python:3.12-slim"

// ImagePullPolicy controls when a sandbox backend should pull its image.
type ImagePullPolicy string

const (
	ImagePullPolicyUnspecified  ImagePullPolicy = ""
	ImagePullPolicyIfNotPresent ImagePullPolicy = "if_not_present"
	ImagePullPolicyAlways       ImagePullPolicy = "always"
	ImagePullPolicyNever        ImagePullPolicy = "never"
)

// SandboxExecutionPolicy describes shared execution limits.
type SandboxExecutionPolicy struct {
	CommandTimeoutSeconds int32
	SetupTimeoutSeconds   int32
	StartupTimeoutSeconds int32
	MaxOutputBytes        int64
}

// SandboxEnvVar describes one static environment variable for sandbox startup.
type SandboxEnvVar struct {
	Name  string
	Value string
}

// ImageReference identifies one sandbox image.
type ImageReference struct {
	Reference  string
	PullPolicy ImagePullPolicy
}

// LocalSandboxSpec describes the local workspace-backed sandbox backend.
type LocalSandboxSpec struct{}

// DockerResourceSpec describes Docker runtime limits exposed to authored sandbox configs.
type DockerResourceSpec struct {
	CPU       string
	Memory    string
	ShmSize   string
	PidsLimit int64
}

// DockerSandboxSpec describes one Docker-backed sandbox.
type DockerSandboxSpec struct {
	Image     ImageReference
	Resources DockerResourceSpec
}

// KubernetesResourceRequirements describes container resource requests and limits.
type KubernetesResourceRequirements struct {
	Requests map[string]string
	Limits   map[string]string
}

// KubernetesSandboxSpec describes one Kubernetes-backed sandbox.
type KubernetesSandboxSpec struct {
	Image     ImageReference
	Resources KubernetesResourceRequirements
}

// SandboxSpec describes one concrete executable sandbox configuration.
type SandboxSpec struct {
	Execution     SandboxExecutionPolicy
	Env           []SandboxEnvVar
	SetupCommands []string
	Local         *LocalSandboxSpec
	Docker        *DockerSandboxSpec
	Kubernetes    *KubernetesSandboxSpec
}

// Empty reports whether the sandbox spec is unset.
func (s SandboxSpec) Empty() bool {
	return s.Local == nil &&
		s.Docker == nil &&
		s.Kubernetes == nil &&
		len(s.Env) == 0 &&
		len(s.SetupCommands) == 0 &&
		s.Execution == (SandboxExecutionPolicy{})
}

// BackendKind reports the selected concrete backend kind, if any.
func (s SandboxSpec) BackendKind() SandboxBackendKind {
	switch {
	case s.Local != nil:
		return SandboxBackendKindLocal
	case s.Docker != nil:
		return SandboxBackendKindDocker
	case s.Kubernetes != nil:
		return SandboxBackendKindKubernetes
	default:
		return ""
	}
}

// CloneSandboxSpec returns a deep copy of one sandbox spec.
func CloneSandboxSpec(spec SandboxSpec) SandboxSpec {
	cloned := SandboxSpec{
		Execution:     spec.Execution,
		Env:           cloneSandboxEnvVars(spec.Env),
		SetupCommands: cloneStrings(spec.SetupCommands),
	}
	if spec.Local != nil {
		local := *spec.Local
		cloned.Local = &local
	}
	if spec.Docker != nil {
		docker := *spec.Docker
		cloned.Docker = &docker
	}
	if spec.Kubernetes != nil {
		kubernetes := *spec.Kubernetes
		kubernetes.Resources = KubernetesResourceRequirements{
			Requests: cloneStringMap(spec.Kubernetes.Resources.Requests),
			Limits:   cloneStringMap(spec.Kubernetes.Resources.Limits),
		}
		cloned.Kubernetes = &kubernetes
	}
	return cloned
}

func cloneSandboxEnvVars(env []SandboxEnvVar) []SandboxEnvVar {
	cloned := make([]SandboxEnvVar, 0, len(env))
	for _, item := range env {
		cloned = append(cloned, SandboxEnvVar{
			Name:  item.Name,
			Value: item.Value,
		})
	}
	return cloned
}

// NormalizeSandboxSpec validates and canonicalizes one explicit sandbox spec.
func NormalizeSandboxSpec(spec SandboxSpec) (SandboxSpec, error) {
	cloned := CloneSandboxSpec(spec)

	backendCount := 0
	if cloned.Local != nil {
		backendCount++
	}
	if cloned.Docker != nil {
		backendCount++
	}
	if cloned.Kubernetes != nil {
		backendCount++
	}
	if backendCount > 1 {
		return SandboxSpec{}, fmt.Errorf("sandbox must define exactly one backend")
	}

	for index, envVar := range cloned.Env {
		name := strings.TrimSpace(envVar.Name)
		if name == "" {
			return SandboxSpec{}, fmt.Errorf("sandbox env[%d] name cannot be empty", index)
		}
		cloned.Env[index].Name = name
	}

	for index, command := range cloned.SetupCommands {
		trimmed := strings.TrimSpace(command)
		if trimmed == "" {
			return SandboxSpec{}, fmt.Errorf("sandbox setup_commands[%d] cannot be empty", index)
		}
		cloned.SetupCommands[index] = trimmed
	}

	if cloned.Execution.CommandTimeoutSeconds < 0 {
		return SandboxSpec{}, fmt.Errorf("sandbox execution command_timeout_seconds must be non-negative")
	}
	if cloned.Execution.SetupTimeoutSeconds < 0 {
		return SandboxSpec{}, fmt.Errorf("sandbox execution setup_timeout_seconds must be non-negative")
	}
	if cloned.Execution.StartupTimeoutSeconds < 0 {
		return SandboxSpec{}, fmt.Errorf("sandbox execution startup_timeout_seconds must be non-negative")
	}
	if cloned.Execution.MaxOutputBytes < 0 {
		return SandboxSpec{}, fmt.Errorf("sandbox execution max_output_bytes must be non-negative")
	}

	switch {
	case cloned.Local != nil:
		return cloned, nil
	case cloned.Docker != nil:
		cloned.Docker.Image.Reference = strings.TrimSpace(cloned.Docker.Image.Reference)
		if cloned.Docker.Image.Reference == "" {
			return SandboxSpec{}, fmt.Errorf("sandbox docker image cannot be empty")
		}
		if err := validateImagePullPolicy(cloned.Docker.Image.PullPolicy, "sandbox docker image pull_policy"); err != nil {
			return SandboxSpec{}, err
		}
		cloned.Docker.Resources.CPU = strings.TrimSpace(cloned.Docker.Resources.CPU)
		cloned.Docker.Resources.Memory = strings.TrimSpace(cloned.Docker.Resources.Memory)
		cloned.Docker.Resources.ShmSize = strings.TrimSpace(cloned.Docker.Resources.ShmSize)
		if cloned.Docker.Resources.PidsLimit < 0 {
			return SandboxSpec{}, fmt.Errorf("sandbox docker resources pids_limit must be non-negative")
		}
		return cloned, nil
	case cloned.Kubernetes != nil:
		cloned.Kubernetes.Image.Reference = strings.TrimSpace(cloned.Kubernetes.Image.Reference)
		if cloned.Kubernetes.Image.Reference == "" {
			return SandboxSpec{}, fmt.Errorf("sandbox kubernetes image cannot be empty")
		}
		if err := validateImagePullPolicy(cloned.Kubernetes.Image.PullPolicy, "sandbox kubernetes image pull_policy"); err != nil {
			return SandboxSpec{}, err
		}
		requests, err := normalizeSandboxStringMap(
			cloned.Kubernetes.Resources.Requests,
			"sandbox kubernetes resources requests",
		)
		if err != nil {
			return SandboxSpec{}, err
		}
		limits, err := normalizeSandboxStringMap(
			cloned.Kubernetes.Resources.Limits,
			"sandbox kubernetes resources limits",
		)
		if err != nil {
			return SandboxSpec{}, err
		}
		cloned.Kubernetes.Resources.Requests = requests
		cloned.Kubernetes.Resources.Limits = limits
		return cloned, nil
	default:
		if cloned.Empty() {
			return SandboxSpec{}, nil
		}
		return SandboxSpec{}, fmt.Errorf("sandbox backend must be set")
	}
}

// LegacySandboxSpec converts the old implicit sandbox shape into the explicit spec.
func LegacySandboxSpec(
	image string,
	resources map[string]string,
	init []string,
) (SandboxSpec, error) {
	trimmedImage := strings.TrimSpace(image)
	clonedResources, err := normalizeSandboxStringMap(resources, "sandbox resources")
	if err != nil {
		return SandboxSpec{}, err
	}

	backend := ""
	for _, key := range []string{"backend", "kind", "provider"} {
		if value, ok := clonedResources[key]; ok {
			backend = normalizeLegacySandboxBackend(value)
			break
		}
	}
	if backend == "" {
		if trimmedImage != "" {
			backend = string(SandboxBackendKindDocker)
		} else {
			backend = string(SandboxBackendKindLocal)
		}
	}

	spec := SandboxSpec{
		Execution: SandboxExecutionPolicy{
			MaxOutputBytes: parseLegacySandboxInt64(clonedResources["max_output_bytes"]),
		},
		SetupCommands: cloneStrings(init),
	}
	switch SandboxBackendKind(backend) {
	case SandboxBackendKindLocal:
		spec.Local = &LocalSandboxSpec{}
	case SandboxBackendKindDocker:
		imageRef := trimmedImage
		if imageRef == "" {
			imageRef = DefaultSandboxImage
		}
		spec.Docker = &DockerSandboxSpec{
			Image: ImageReference{Reference: imageRef},
			Resources: DockerResourceSpec{
				CPU:       clonedResources["cpu"],
				Memory:    clonedResources["memory"],
				ShmSize:   clonedResources["shm_size"],
				PidsLimit: parseLegacySandboxInt64(clonedResources["pids_limit"]),
			},
		}
	case SandboxBackendKindKubernetes:
		imageRef := trimmedImage
		if imageRef == "" {
			imageRef = DefaultSandboxImage
		}
		limits := map[string]string{}
		for _, key := range []string{"cpu", "memory"} {
			if value := strings.TrimSpace(clonedResources[key]); value != "" {
				limits[key] = value
			}
		}
		spec.Kubernetes = &KubernetesSandboxSpec{
			Image:     ImageReference{Reference: imageRef},
			Resources: KubernetesResourceRequirements{Limits: limits},
		}
	default:
		return SandboxSpec{}, fmt.Errorf(
			"sandbox backend %q is not supported",
			backend,
		)
	}

	return NormalizeSandboxSpec(spec)
}

func normalizeLegacySandboxBackend(value string) string {
	normalized := strings.ToLower(strings.TrimSpace(value))
	switch normalized {
	case "filesystem", "shell":
		return string(SandboxBackendKindLocal)
	case "k8s":
		return string(SandboxBackendKindKubernetes)
	case "kubernetes":
		return string(SandboxBackendKindKubernetes)
	default:
		return normalized
	}
}

func validateImagePullPolicy(policy ImagePullPolicy, fieldName string) error {
	switch strings.TrimSpace(string(policy)) {
	case "", string(ImagePullPolicyIfNotPresent), string(ImagePullPolicyAlways), string(ImagePullPolicyNever):
		return nil
	default:
		return fmt.Errorf("%s is not supported", fieldName)
	}
}

func normalizeSandboxStringMap(values map[string]string, fieldName string) (map[string]string, error) {
	if len(values) == 0 {
		return nil, nil
	}
	normalized := make(map[string]string, len(values))
	for key, value := range values {
		trimmedKey := strings.TrimSpace(key)
		if trimmedKey == "" {
			return nil, fmt.Errorf("%s key cannot be empty", fieldName)
		}
		trimmedValue := strings.TrimSpace(value)
		if trimmedValue == "" {
			return nil, fmt.Errorf("%s[%s] cannot be empty", fieldName, trimmedKey)
		}
		normalized[trimmedKey] = trimmedValue
	}
	return normalized, nil
}

func parseLegacySandboxInt64(value string) int64 {
	value = strings.TrimSpace(value)
	if value == "" {
		return 0
	}
	var parsed int64
	_, _ = fmt.Sscan(value, &parsed)
	return parsed
}

func cloneStrings(values []string) []string {
	cloned := make([]string, 0, len(values))
	cloned = append(cloned, values...)
	return cloned
}

func cloneStringMap(values map[string]string) map[string]string {
	if len(values) == 0 {
		return nil
	}
	cloned := make(map[string]string, len(values))
	for key, value := range values {
		cloned[key] = value
	}
	return cloned
}
