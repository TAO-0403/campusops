CREATE TABLE request_attachments (
    id BIGSERIAL PRIMARY KEY,
    request_id BIGINT NOT NULL UNIQUE REFERENCES purchase_requests(id) ON DELETE CASCADE,
    original_filename TEXT NOT NULL,
    storage_id TEXT NOT NULL UNIQUE CHECK (storage_id ~ '^[0-9a-f]{64}$'),
    file_size BIGINT NOT NULL CHECK (file_size > 0 AND file_size <= 5242880),
    uploaded_by BIGINT NOT NULL REFERENCES users(id),
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE request_events
    DROP CONSTRAINT request_events_event_type_check;

ALTER TABLE request_events
    ADD CONSTRAINT request_events_event_type_check
    CHECK (event_type IN (
        'Created', 'Updated', 'Submitted', 'Returned', 'Resubmitted', 'Approved',
        'AttachmentUploaded', 'AttachmentReplaced', 'AttachmentDeleted'
    ));
