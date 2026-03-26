package runtimeclient

import "errors"

var (
	// ErrNotFound indicates the requested runtime-side resource does not exist.
	ErrNotFound = errors.New("runtime resource not found")
)
