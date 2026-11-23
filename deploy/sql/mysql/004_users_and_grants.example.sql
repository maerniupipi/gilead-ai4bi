-- TEMPLATE: replace both passwords and restrict '%' to the application/laboratory hosts.
-- Do not import unchanged. Application login accounts are created by the backend, not here.
CREATE USER 'gilead_react_app'@'%' IDENTIFIED BY 'REPLACE_WITH_APP_DATABASE_PASSWORD';
CREATE USER 'gilead_lab_reader'@'%' IDENTIFIED BY 'REPLACE_WITH_BUSINESS_READONLY_PASSWORD';
GRANT ALL PRIVILEGES ON `gilead_agent_loop`.* TO 'gilead_react_app'@'%';
GRANT SELECT, SHOW VIEW ON `gilead_poc`.* TO 'gilead_lab_reader'@'%';
