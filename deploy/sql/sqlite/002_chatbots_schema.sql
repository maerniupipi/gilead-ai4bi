-- Generated schema only. The application seeds its assistant directory at startup.
PRAGMA foreign_keys=ON;

CREATE TABLE chatbots (id TEXT PRIMARY KEY, body TEXT NOT NULL);

CREATE TABLE personal_workbooks (workbook_id TEXT PRIMARY KEY, chatbot_id TEXT NOT NULL, owner_id TEXT NOT NULL);

CREATE TABLE workbook_uploads (id TEXT PRIMARY KEY, chatbot_id TEXT NOT NULL, owner_id TEXT NOT NULL, fingerprint TEXT NOT NULL, status TEXT NOT NULL, body TEXT NOT NULL, content BLOB);

CREATE TABLE workbooks (id TEXT PRIMARY KEY, body TEXT NOT NULL);

CREATE INDEX ix_personal_workbooks_owner ON personal_workbooks(chatbot_id, owner_id);

CREATE INDEX ix_workbook_uploads_owner ON workbook_uploads(chatbot_id, owner_id, status);
