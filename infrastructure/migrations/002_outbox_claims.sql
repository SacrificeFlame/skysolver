BEGIN;

ALTER TABLE transactional_outbox
    ADD COLUMN claimed_at timestamptz,
    ADD COLUMN claimed_by text;

CREATE INDEX transactional_outbox_claimable
    ON transactional_outbox (next_attempt_at, created_at)
    WHERE published_at IS NULL AND claimed_at IS NULL;

COMMIT;
