package registry

import "errors"

var (
	// ErrInvalid indicates the resource payload or references are invalid.
	ErrInvalid = errors.New("invalid resource")
)
