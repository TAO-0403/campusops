CREATE TABLE email_outbox (
    id BIGSERIAL PRIMARY KEY,
    request_event_id BIGINT NOT NULL REFERENCES request_events(id) ON DELETE CASCADE,
    recipient_user_id BIGINT NOT NULL REFERENCES users(id),
    recipient_email TEXT NOT NULL,
    subject TEXT NOT NULL,
    text_body TEXT NOT NULL,
    html_body TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'sending', 'sent')),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    locked_until TIMESTAMPTZ,
    claim_token UUID,
    sent_at TIMESTAMPTZ,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (request_event_id, recipient_user_id),
    CHECK ((status = 'sending') = (claim_token IS NOT NULL)),
    CHECK ((status = 'sending') = (locked_until IS NOT NULL)),
    CHECK ((status = 'sent') = (sent_at IS NOT NULL))
);

CREATE INDEX email_outbox_pending_idx ON email_outbox (next_attempt_at, id)
    WHERE status = 'pending';
CREATE INDEX email_outbox_expired_claim_idx ON email_outbox (locked_until, id)
    WHERE status = 'sending';
