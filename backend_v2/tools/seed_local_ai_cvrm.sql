CREATE DATABASE IF NOT EXISTS AI_CVRM
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE AI_CVRM;

CREATE TABLE IF NOT EXISTS tw_performance_sales_cvh (
  date DATE NOT NULL,
  half_year_flag VARCHAR(4),
  sku_name VARCHAR(256),
  family_code VARCHAR(16),
  family_name VARCHAR(128),
  brand_code VARCHAR(8),
  brand_name VARCHAR(128),
  ta_name VARCHAR(16),
  inst_name VARCHAR(256),
  inst_type VARCHAR(32),
  county_name VARCHAR(128),
  city_name VARCHAR(128),
  province_name VARCHAR(32),
  rsm_name VARCHAR(64),
  rsd_name VARCHAR(64),
  district_name VARCHAR(256),
  region_name VARCHAR(256),
  bu_name VARCHAR(128),
  sub_bu_name VARCHAR(128),
  channel VARCHAR(64),
  sales_val DECIMAL(20,4),
  sales_vol DECIMAL(20,8),
  sales_vol_conversion DECIMAL(20,8),
  sales_vol_standard DECIMAL(20,8),
  decile_key VARCHAR(64)
);

CREATE TABLE IF NOT EXISTS tw_target_cvh (
  date DATE NOT NULL,
  half_year_flag VARCHAR(4),
  family_name VARCHAR(64),
  brand_code VARCHAR(8),
  brand_name VARCHAR(64),
  ta_name VARCHAR(8),
  inst_name VARCHAR(256),
  county_name VARCHAR(64),
  city_name VARCHAR(64),
  province_name VARCHAR(16),
  rsm_name VARCHAR(64),
  rsd_name VARCHAR(64),
  bu_name_report VARCHAR(32),
  target_val DECIMAL(20,2),
  decile_key VARCHAR(64)
);

CREATE TABLE IF NOT EXISTS td_inst_mkt_decile (
  decile_key VARCHAR(64) PRIMARY KEY,
  decile INT
);

CREATE TABLE IF NOT EXISTS tw_demand_sales_cvh_org (
  org_key VARCHAR(32),
  bu_name VARCHAR(16),
  region_name VARCHAR(64),
  date DATE NOT NULL,
  year_quater VARCHAR(8),
  half_year VARCHAR(8),
  brand_code VARCHAR(8),
  brand_name VARCHAR(32),
  ta_name VARCHAR(8),
  province_name VARCHAR(16),
  sales_vol DECIMAL(20,4),
  sales_val DECIMAL(20,4),
  sales_vol_conversion DECIMAL(20,4),
  sales_vol_standard DECIMAL(20,4)
);

CREATE TABLE IF NOT EXISTS tw_demand_target_cvh_org (
  org_key VARCHAR(32),
  bu_name VARCHAR(16),
  date DATE NOT NULL,
  year_quater VARCHAR(8),
  half_year VARCHAR(8),
  brand_code VARCHAR(8),
  brand_name VARCHAR(32),
  ta_name VARCHAR(8),
  province_name VARCHAR(16),
  target_val DECIMAL(20,8)
);

CREATE TABLE IF NOT EXISTS td_external_market_ta (
  TA VARCHAR(32),
  DATA_SOURCE VARCHAR(32),
  value_type VARCHAR(16)
);

CREATE TABLE IF NOT EXISTS td_external_org (
  audit_cod VARCHAR(16),
  market VARCHAR(64),
  DATA_SOURCE VARCHAR(32),
  region_name VARCHAR(32)
);

CREATE TABLE IF NOT EXISTS td_external_target_ins_level (
  target_ins_level VARCHAR(32),
  DATA_SOURCE VARCHAR(32)
);

CREATE TABLE IF NOT EXISTS tw_external_fact_sales (
  audit_cod VARCHAR(16),
  market VARCHAR(64),
  DATA_SOURCE VARCHAR(32),
  value_type VARCHAR(16),
  brand_name VARCHAR(64),
  date DATE NOT NULL,
  sales DECIMAL(20,4)
);

DELETE FROM tw_performance_sales_cvh;
DELETE FROM tw_target_cvh;
DELETE FROM td_inst_mkt_decile;
DELETE FROM tw_demand_sales_cvh_org;
DELETE FROM tw_demand_target_cvh_org;
DELETE FROM td_external_market_ta;
DELETE FROM td_external_org;
DELETE FROM td_external_target_ins_level;
DELETE FROM tw_external_fact_sales;

INSERT INTO td_inst_mkt_decile (decile_key, decile) VALUES
  ('2026SH001HB039', 2),
  ('2026BJ001HB039', 3),
  ('2026GD001HB012', 4);

INSERT INTO tw_performance_sales_cvh
(date, half_year_flag, sku_name, family_code, family_name, brand_code, brand_name, ta_name,
 inst_name, inst_type, county_name, city_name, province_name, rsm_name, rsd_name,
 district_name, region_name, bu_name, sub_bu_name, channel,
 sales_val, sales_vol, sales_vol_conversion, sales_vol_standard, decile_key)
VALUES
  ('2025-01-01','H1','Forxiga 10mg*14','CV24','Forxiga','B039','Forxiga','DM','上海新华医院','医院','徐汇区','上海市','上海','潘荣','孙方方','上海心肾代综合组','上海心肾代综合大区','CVRM','CVRM','BU', 820000, 12000, 168000, 12000, '2026SH001HB039'),
  ('2025-06-01','H1','Forxiga 10mg*14','CV24','Forxiga','B039','Forxiga','DM','上海新华医院','医院','徐汇区','上海市','上海','潘荣','孙方方','上海心肾代综合组','上海心肾代综合大区','CVRM','CVRM','BU', 910000, 13200, 184800, 13200, '2026SH001HB039'),
  ('2025-12-01','H2','Forxiga 10mg*14','CV24','Forxiga','B039','Forxiga','DM','北京协和医院','医院','东城区','北京市','北京','魏勇','陈娅','北京心肾代综合组','北京心肾代综合大区','CVRM','CVRM','BU', 980000, 14000, 196000, 14000, '2026BJ001HB039'),
  ('2026-01-01','H1','Forxiga 10mg*14','CV24','Forxiga','B039','Forxiga','DM','上海新华医院','医院','徐汇区','上海市','上海','潘荣','孙方方','上海心肾代综合组','上海心肾代综合大区','CVRM','CVRM','BU', 1050000, 15000, 210000, 15000, '2026SH001HB039'),
  ('2026-03-01','H1','Forxiga 10mg*14','CV24','Forxiga','B039','Forxiga','DM','北京协和医院','医院','东城区','北京市','北京','魏勇','陈娅','北京心肾代综合组','北京心肾代综合大区','CVRM','CVRM','BU', 1120000, 16000, 224000, 16000, '2026BJ001HB039'),
  ('2026-07-01','H2','Forxiga 10mg*14','CV24','Forxiga','B039','Forxiga','DM','上海新华医院','医院','徐汇区','上海市','上海','潘荣','孙方方','上海心肾代综合组','上海心肾代综合大区','CVRM','CVRM','BU', 1180000, 16800, 235200, 16800, '2026SH001HB039'),
  ('2026-07-01','H2','Betaloc ZOK 50mg*14s*2','CV09','Betaloc ZOK','B012','Betaloc ZOK','CV','广东人民医院','医院','越秀区','广州市','广东','郝件','刘贵平','广东心肾代组','广东心肾代大区','CVRM','CVRM','BU', 430000, 8000, 224000, 8000, '2026GD001HB012');

INSERT INTO tw_target_cvh
(date, half_year_flag, family_name, brand_code, brand_name, ta_name, inst_name, county_name, city_name, province_name, rsm_name, rsd_name, bu_name_report, target_val, decile_key)
VALUES
  ('2026-01-01','H1','Forxiga','B039','Forxiga','DM','上海新华医院','徐汇区','上海市','上海','潘荣','孙方方','CVRM', 1000000, '2026SH001HB039'),
  ('2026-03-01','H1','Forxiga','B039','Forxiga','DM','北京协和医院','东城区','北京市','北京','魏勇','陈娅','CVRM', 1080000, '2026BJ001HB039'),
  ('2026-07-01','H2','Forxiga','B039','Forxiga','DM','上海新华医院','徐汇区','上海市','上海','潘荣','孙方方','CVRM', 1100000, '2026SH001HB039'),
  ('2026-07-01','H2','Betaloc ZOK','B012','Betaloc ZOK','CV','广东人民医院','越秀区','广州市','广东','郝件','刘贵平','CVRM', 400000, '2026GD001HB012');

INSERT INTO tw_demand_sales_cvh_org
(org_key, bu_name, region_name, date, year_quater, half_year, brand_code, brand_name, ta_name, province_name, sales_vol, sales_val, sales_vol_conversion, sales_vol_standard)
VALUES
  ('202607_RD_C40020','CVRM','上海心肾代综合大区','2026-07-01','2026Q3','2026H2','B039','Forxiga','DM','上海', 9000, 620000, 126000, 9000),
  ('202607_RD_C40021','CVRM','北京心肾代综合大区','2026-07-01','2026Q3','2026H2','B039','Forxiga','DM','北京', 8200, 570000, 114800, 8200);

INSERT INTO tw_demand_target_cvh_org
(org_key, bu_name, date, year_quater, half_year, brand_code, brand_name, ta_name, province_name, target_val)
VALUES
  ('202607_RD_C40020','CVRM','2026-07-01','2026Q3','2026H2','B039','Forxiga','DM','上海', 600000),
  ('202607_RD_C40021','CVRM','2026-07-01','2026Q3','2026H2','B039','Forxiga','DM','北京', 560000);

INSERT INTO td_external_market_ta (TA, DATA_SOURCE, value_type) VALUES
  ('DM','AIA(Monthly)','PDOT'),
  ('CV','CHPA','RMB');

INSERT INTO td_external_org (audit_cod, market, DATA_SOURCE, region_name) VALUES
  ('SH','NIAD','AIA(Monthly)','上海'),
  ('BJ','NIAD','AIA(Monthly)','北京');

INSERT INTO td_external_target_ins_level (target_ins_level, DATA_SOURCE) VALUES
  ('NA','AIA(Monthly)');

INSERT INTO tw_external_fact_sales
(audit_cod, market, DATA_SOURCE, value_type, brand_name, date, sales)
VALUES
  ('SH','NIAD','AIA(Monthly)','PDOT','Forxiga','2026-07-01', 188000),
  ('BJ','NIAD','AIA(Monthly)','PDOT','Forxiga','2026-07-01', 164000),
  ('SH','NIAD','AIA(Monthly)','PDOT','Market','2026-07-01', 920000);
