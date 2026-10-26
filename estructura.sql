--
-- PostgreSQL database dump
--

\restrict QKRFB4eEHbVolH7qLOWf4HyXZftpgh8kLvj3V6mySf8ENiYmgDj4uDPGILf4eVu

-- Dumped from database version 18.4
-- Dumped by pg_dump version 18.4

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
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
-- Name: equipos; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.equipos (
    id integer NOT NULL,
    fecha timestamp without time zone,
    juzgado character varying(100),
    edificio character varying(100),
    piso character varying(50),
    hostname character varying(100),
    service_tag character varying(100),
    nombre_usuario character varying(150),
    rol character varying(100),
    marca character varying(100),
    modelo character varying(100),
    procesador character varying(150),
    tipo_disco character varying(20),
    tamano_disco character varying(50),
    tipo_ram character varying(20),
    tamano_memoria character varying(50),
    cod_act_pc character varying(100),
    marca_impresora character varying(100),
    modelo_impresora character varying(100),
    conexion_impresora character varying(10),
    cod_act_imp character varying(100),
    tipo_equipo character varying(20),
    fecha_bios date,
    version_bios character varying(100),
    so_nombre character varying(100),
    so_build character varying(30),
    fecha_instalacion_so date,
    cpu_nucleos smallint,
    cpu_hilos smallint,
    cpu_mhz integer,
    ram_slots_usados smallint,
    ram_slots_total smallint,
    ram_mhz integer,
    disco_salud character varying(30),
    disco_smart character varying(20),
    disco_desgaste_pct smallint,
    disco_horas_uso integer,
    disco_libre_gb integer,
    tpm_version character varying(10),
    secure_boot character varying(20),
    ip character varying(45),
    mac character varying(20),
    dominio character varying(100)
);


ALTER TABLE public.equipos OWNER TO postgres;

--
-- Name: equipos_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.equipos_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.equipos_id_seq OWNER TO postgres;

--
-- Name: equipos_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.equipos_id_seq OWNED BY public.equipos.id;


--
-- Name: v_obsolescencia; Type: VIEW; Schema: public; Owner: postgres
--

CREATE VIEW public.v_obsolescencia AS
 SELECT id,
    hostname,
    juzgado,
    cod_act_pc,
    round((((CURRENT_DATE - fecha_bios))::numeric / 365.25), 1) AS antiguedad_anios,
    LEAST(100, ((((((
        CASE
            WHEN (fecha_bios IS NULL) THEN 0
            WHEN ((CURRENT_DATE - fecha_bios) > (365 * 7)) THEN 40
            WHEN ((CURRENT_DATE - fecha_bios) > (365 * 5)) THEN 25
            WHEN ((CURRENT_DATE - fecha_bios) > (365 * 3)) THEN 10
            ELSE 0
        END +
        CASE
            WHEN ((tipo_disco)::text = 'HDD'::text) THEN 20
            ELSE 0
        END) +
        CASE
            WHEN ((tamano_memoria)::text ~~* '%MB%'::text) THEN 15
            WHEN (COALESCE((NULLIF(regexp_replace((tamano_memoria)::text, '\D'::text, ''::text, 'g'::text), ''::text))::integer, 0) < 8) THEN 15
            ELSE 0
        END) +
        CASE
            WHEN ((tpm_version IS NOT NULL) AND ((tpm_version)::text !~~ '2.0%'::text)) THEN 10
            ELSE 0
        END) +
        CASE
            WHEN ((disco_salud IS NOT NULL) AND ((disco_salud)::text <> 'Healthy'::text)) THEN 30
            ELSE 0
        END) +
        CASE
            WHEN ((disco_smart)::text = 'FALLA'::text) THEN 30
            ELSE 0
        END) +
        CASE
            WHEN (COALESCE((disco_desgaste_pct)::integer, 0) >= 80) THEN 20
            ELSE 0
        END)) AS score_obsolescencia
   FROM public.equipos;


ALTER VIEW public.v_obsolescencia OWNER TO postgres;

--
-- Name: equipos id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.equipos ALTER COLUMN id SET DEFAULT nextval('public.equipos_id_seq'::regclass);


--
-- Name: equipos equipos_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.equipos
    ADD CONSTRAINT equipos_pkey PRIMARY KEY (id);


--
-- Name: equipos equipos_service_tag_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.equipos
    ADD CONSTRAINT equipos_service_tag_key UNIQUE (service_tag);


--
-- PostgreSQL database dump complete
--

\unrestrict QKRFB4eEHbVolH7qLOWf4HyXZftpgh8kLvj3V6mySf8ENiYmgDj4uDPGILf4eVu

