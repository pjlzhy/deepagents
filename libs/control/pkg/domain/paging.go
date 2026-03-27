package domain

// PageQuery describes one generic page-based list query.
type PageQuery struct {
	PageSize   int32
	PageNumber int32
}

// PageMetadata captures the metadata of one page-based list result.
type PageMetadata struct {
	PageSize   int32
	PageNumber int32
	TotalSize  int32
	TotalPages int32
}

// ResourcePage captures one generic page-based list result.
type ResourcePage[T any] struct {
	Items []T
	PageMetadata
}
