-- MySQL 8.0+: run as a database administrator. Change database names if required.
-- gilead_agent_loop: users, conversations, jobs, metadata, configuration and audit.
-- gilead_poc: the six optional Gilead business tables; import your business data separately.
CREATE DATABASE IF NOT EXISTS `gilead_agent_loop`
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS `gilead_poc`
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
