-- Schema version 4 (Faz 13f, Mimari §6.2, D-084): why a provider is paused, so a used-up
-- quota reads differently from repeated errors. Never edit this file; add a new migration.

ALTER TABLE health ADD COLUMN open_reason TEXT;  -- quota | auth | errors; NULL: not paused
