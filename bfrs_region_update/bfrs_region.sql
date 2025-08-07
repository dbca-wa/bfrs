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
-- Name: bfrs_region; Type: TABLE; Schema: public; Owner: bfrs_dev
--

CREATE TABLE public.bfrs_region (
    id integer NOT NULL,
    name character varying(64) NOT NULL,
    forest_region boolean NOT NULL,
    geometry public.geometry,
    dbca boolean
);


ALTER TABLE public.bfrs_region OWNER TO bfrs_dev;

--
-- Name: bfrs_region_id_seq; Type: SEQUENCE; Schema: public; Owner: bfrs_dev
--

CREATE SEQUENCE public.bfrs_region_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.bfrs_region_id_seq OWNER TO bfrs_dev;

--
-- Name: bfrs_region_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: bfrs_dev
--

ALTER SEQUENCE public.bfrs_region_id_seq OWNED BY public.bfrs_region.id;


--
-- Name: bfrs_region id; Type: DEFAULT; Schema: public; Owner: bfrs_dev
--

ALTER TABLE ONLY public.bfrs_region ALTER COLUMN id SET DEFAULT nextval('public.bfrs_region_id_seq'::regclass);


--
-- Name: bfrs_region bfrs_region_name_key; Type: CONSTRAINT; Schema: public; Owner: bfrs_dev
--

ALTER TABLE ONLY public.bfrs_region
    ADD CONSTRAINT bfrs_region_name_key UNIQUE (name);


--
-- Name: bfrs_region bfrs_region_pkey; Type: CONSTRAINT; Schema: public; Owner: bfrs_dev
--

ALTER TABLE ONLY public.bfrs_region
    ADD CONSTRAINT bfrs_region_pkey PRIMARY KEY (id);


--
-- Name: bfrs_region_name_719c5fa2_like; Type: INDEX; Schema: public; Owner: bfrs_dev
--

CREATE INDEX bfrs_region_name_719c5fa2_like ON public.bfrs_region USING btree (name varchar_pattern_ops);


--
-- Name: idx_bfrs_region_geometry; Type: INDEX; Schema: public; Owner: bfrs_dev
--

CREATE INDEX idx_bfrs_region_geometry ON public.bfrs_region USING gist (geometry);


--
-- PostgreSQL database dump complete
--

