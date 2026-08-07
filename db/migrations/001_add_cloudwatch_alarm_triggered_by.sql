-- Add cloudwatch_alarm to triggered_by enum (existing deployments).
-- Safe to run multiple times: skips if value already exists.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_enum e
        JOIN pg_type t ON e.enumtypid = t.oid
        WHERE t.typname = 'triggered_by'
          AND e.enumlabel = 'cloudwatch_alarm'
    ) THEN
        ALTER TYPE triggered_by ADD VALUE 'cloudwatch_alarm';
    END IF;
END
$$;
