package store

import "context"

// Store 表示 control layer 底层持久化能力。
type Store interface {
	Ping(ctx context.Context) error
	Close() error
}

// SQLiteConfig 描述 SQLite store 初始化参数。
type SQLiteConfig struct {
	Path string
}
