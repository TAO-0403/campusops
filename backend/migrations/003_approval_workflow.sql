ALTER TABLE request_events
    DROP CONSTRAINT request_events_event_type_check;

ALTER TABLE request_events
    ADD CONSTRAINT request_events_event_type_check
    CHECK (event_type IN ('Created', 'Updated', 'Submitted', 'Returned', 'Resubmitted', 'Approved'));

ALTER TABLE request_events
    ADD COLUMN comment TEXT;
