package store

import (
	"context"
	"path/filepath"
	"testing"
)

func TestOpenSQLiteInitializesSchema(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "control.sqlite")

	db, err := OpenSQLite(ctx, SQLiteConfig{Path: path})
	if err != nil {
		t.Fatalf("open sqlite store: %v", err)
	}
	defer func() {
		_ = db.Close()
	}()

	if err := db.Ping(ctx); err != nil {
		t.Fatalf("ping sqlite store: %v", err)
	}
	if db.DB() == nil {
		t.Fatal("expected underlying sql.DB")
	}
}
