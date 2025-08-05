--
-- PostgreSQL database dump
--

-- Dumped from database version 11.2 (Debian 11.2-1.pgdg90+1)
-- Dumped by pg_dump version 16.6 (Ubuntu 16.6-0ubuntu0.24.04.1)

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

--
-- Name: reporting_dept_interest; Type: TABLE; Schema: public; Owner: fire
--

CREATE TABLE public.reporting_dept_interest (
    ogc_fid integer NOT NULL,
    loi_pin double precision,
    loi_poly_area double precision,
    loi_identifier character varying(64),
    loi_regno character varying(50),
    loi_tenure character varying(254),
    loi_act character varying(254),
    category character varying(40),
    loi_notes character varying(254),
    loi_prprietor character varying(120),
    shape_length double precision,
    shape_area double precision,
    geometry public.geometry(MultiPolygon,4326)
);


ALTER TABLE public.reporting_dept_interest OWNER TO fire;

--
-- Name: reporting_dept_interest_ogc_fid_seq1; Type: SEQUENCE; Schema: public; Owner: fire
--

CREATE SEQUENCE public.reporting_dept_interest_ogc_fid_seq1
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.reporting_dept_interest_ogc_fid_seq1 OWNER TO fire;

--
-- Name: reporting_dept_interest_ogc_fid_seq1; Type: SEQUENCE OWNED BY; Schema: public; Owner: fire
--

ALTER SEQUENCE public.reporting_dept_interest_ogc_fid_seq1 OWNED BY public.reporting_dept_interest.ogc_fid;


--
-- Name: reporting_dept_interest ogc_fid; Type: DEFAULT; Schema: public; Owner: fire
--

ALTER TABLE ONLY public.reporting_dept_interest ALTER COLUMN ogc_fid SET DEFAULT nextval('public.reporting_dept_interest_ogc_fid_seq1'::regclass);


--
-- Name: reporting_dept_interest reporting_dept_interest_pkey1; Type: CONSTRAINT; Schema: public; Owner: fire
--

ALTER TABLE ONLY public.reporting_dept_interest
    ADD CONSTRAINT reporting_dept_interest_pkey1 PRIMARY KEY (ogc_fid);


--
-- Name: idx_reporting_dept_interest_category_2021; Type: INDEX; Schema: public; Owner: fire
--

CREATE INDEX idx_reporting_dept_interest_category_2021 ON public.reporting_dept_interest USING btree (category);


--
-- Name: reporting_dept_interest_geometry_geom_idx_2021; Type: INDEX; Schema: public; Owner: fire
--

CREATE INDEX reporting_dept_interest_geometry_geom_idx_2021 ON public.reporting_dept_interest USING gist (geometry);

