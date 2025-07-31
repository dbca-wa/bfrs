--
-- PostgreSQL database dump
--

-- Dumped from database version 16.9 (Debian 16.9-1.pgdg120+1)
-- Dumped by pg_dump version 16.9 (Ubuntu 16.9-0ubuntu0.24.04.1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: reporting_dept_managed; Type: TABLE; Schema: public; Owner: bfrs_dev
--

CREATE TABLE public.reporting_dept_managed (
    ogc_fid integer NOT NULL,
    leg_pin double precision,
    leg_poly_area double precision,
    leg_class character varying(3),
    leg_identifier character varying(64),
    leg_purpose character varying(240),
    leg_vesting character varying(240),
    leg_name character varying(240),
    leg_name_status character varying(50),
    leg_iucn character varying(5),
    leg_tenure character varying(254),
    leg_act character varying(254),
    category character varying(40),
    leg_notes character varying(254),
    leg_agreement_party character varying(250),
    leg_classification character varying(100),
    leg_regno character varying(50),
    shape_length double precision,
    shape_area double precision,
    geometry public.geometry(MultiPolygon,4326)
);


ALTER TABLE public.reporting_dept_managed OWNER TO bfrs_dev;

--
-- Name: reporting_dept_managed_ogc_fid_seq1; Type: SEQUENCE; Schema: public; Owner: bfrs_dev
--

CREATE SEQUENCE public.reporting_dept_managed_ogc_fid_seq1
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.reporting_dept_managed_ogc_fid_seq1 OWNER TO bfrs_dev;

--
-- Name: reporting_dept_managed_ogc_fid_seq1; Type: SEQUENCE OWNED BY; Schema: public; Owner: bfrs_dev
--

ALTER SEQUENCE public.reporting_dept_managed_ogc_fid_seq1 OWNED BY public.reporting_dept_managed.ogc_fid;


--
-- Name: reporting_dept_managed ogc_fid; Type: DEFAULT; Schema: public; Owner: bfrs_dev
--

ALTER TABLE ONLY public.reporting_dept_managed ALTER COLUMN ogc_fid SET DEFAULT nextval('public.reporting_dept_managed_ogc_fid_seq1'::regclass);


--
-- Name: reporting_dept_managed reporting_dept_managed_pkey1; Type: CONSTRAINT; Schema: public; Owner: bfrs_dev
--

ALTER TABLE ONLY public.reporting_dept_managed
    ADD CONSTRAINT reporting_dept_managed_pkey1 PRIMARY KEY (ogc_fid);


--
-- Name: idx_reporting_dept_managed_category_2021; Type: INDEX; Schema: public; Owner: bfrs_dev
--

CREATE INDEX idx_reporting_dept_managed_category_2021 ON public.reporting_dept_managed USING btree (category);


--
-- Name: reporting_dept_managed_geometry_geom_idx_2021; Type: INDEX; Schema: public; Owner: bfrs_dev
--

CREATE INDEX reporting_dept_managed_geometry_geom_idx_2021 ON public.reporting_dept_managed USING gist (geometry);


--
-- PostgreSQL database dump complete
--

