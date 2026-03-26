package registry

import "errors"

var (
	// ErrNotFound 表示请求的资源不存在。
	ErrNotFound = errors.New("resource not found")

	// ErrConflict 表示资源存在依赖冲突，无法执行删除或覆盖动作。
	ErrConflict = errors.New("resource conflict")
)
