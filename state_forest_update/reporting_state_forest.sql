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
-- Name: reporting_state_forest; Type: TABLE; Schema: public; Owner: fire
--

CREATE TABLE public.reporting_state_forest (
    objectid integer NOT NULL,
    fbr_plantation_classification character varying(33),
    fbr_tenure_category character varying(40),
    fbr_fire_report_classification character varying(40),
    shape_length double precision,
    shape_area double precision,
    shape public.geometry(MultiPolygon,4326)
);


ALTER TABLE public.reporting_state_forest OWNER TO fire;

--
-- Name: reporting_state_forest_objectid_seq1; Type: SEQUENCE; Schema: public; Owner: fire
--

CREATE SEQUENCE public.reporting_state_forest_objectid_seq1
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.reporting_state_forest_objectid_seq1 OWNER TO fire;

--
-- Name: reporting_state_forest_objectid_seq1; Type: SEQUENCE OWNED BY; Schema: public; Owner: fire
--

ALTER SEQUENCE public.reporting_state_forest_objectid_seq1 OWNED BY public.reporting_state_forest.objectid;


--
-- Name: reporting_state_forest objectid; Type: DEFAULT; Schema: public; Owner: fire
--

ALTER TABLE ONLY public.reporting_state_forest ALTER COLUMN objectid SET DEFAULT nextval('public.reporting_state_forest_objectid_seq1'::regclass);


--
-- Name: reporting_state_forest reporting_state_forest_pkey1; Type: CONSTRAINT; Schema: public; Owner: fire
--

ALTER TABLE ONLY public.reporting_state_forest
    ADD CONSTRAINT reporting_state_forest_pkey1 PRIMARY KEY (objectid);


--
-- Name: idx_reporting_state_forest_type_2021; Type: INDEX; Schema: public; Owner: fire
--

CREATE INDEX idx_reporting_state_forest_type_2021 ON public.reporting_state_forest USING btree (fbr_fire_report_classification);


--
-- Name: reporting_state_forest_shape_geom_idx_2021; Type: INDEX; Schema: public; Owner: fire
--

CREATE INDEX reporting_state_forest_shape_geom_idx_2021 ON public.reporting_state_forest USING gist (shape);


--
-- PostgreSQL database dump complete
--

