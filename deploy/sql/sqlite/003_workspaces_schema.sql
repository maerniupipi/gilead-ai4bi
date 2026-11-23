-- Generated schema only. The application seeds its assistant directory at startup.
PRAGMA foreign_keys=ON;

CREATE TABLE board_items (
                    id TEXT PRIMARY KEY,
                    board_id TEXT NOT NULL REFERENCES boards(id) ON DELETE CASCADE,
                    fingerprint TEXT NOT NULL, title TEXT NOT NULL, kind TEXT NOT NULL,
                    width TEXT NOT NULL, position INTEGER NOT NULL,
                    source TEXT NOT NULL, snapshot TEXT NOT NULL, created_at TEXT NOT NULL,
                    UNIQUE(board_id,fingerprint)
                );

CREATE TABLE board_members (
                    board_id TEXT NOT NULL REFERENCES boards(id) ON DELETE CASCADE,
                    user_id TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('viewer','editor')),
                    PRIMARY KEY(board_id,user_id)
                );

CREATE TABLE boards (
                    id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, name TEXT NOT NULL,
                    description TEXT NOT NULL, theme TEXT NOT NULL, version INTEGER NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );

CREATE INDEX ix_board_item_position ON board_items(board_id,position);

CREATE INDEX ix_board_member_user ON board_members(user_id);
