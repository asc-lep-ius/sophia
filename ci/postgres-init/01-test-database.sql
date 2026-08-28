-- Runs once on first initialisation of the local development volume.
-- The test suite uses a separate database so a test run can truncate freely
-- without touching development data.
CREATE DATABASE sophia_test OWNER sophia;
