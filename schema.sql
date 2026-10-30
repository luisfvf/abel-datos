-- Esquema idempotente: el servidor lo ejecuta al arrancar (se puede correr muchas veces).
-- Equivale a estructura.sql, sin los comandos propios de pg_dump/psql.

CREATE TABLE IF NOT EXISTS equipos (
    id serial PRIMARY KEY,
    fecha timestamp without time zone,
    juzgado character varying(100),
    edificio character varying(100),
    piso character varying(50),
    hostname character varying(100),
    service_tag character varying(100) UNIQUE,
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
    dominio character varying(100),
    observacion text
);

-- Columnas agregadas después de la primera versión (para bases ya creadas)
ALTER TABLE equipos ADD COLUMN IF NOT EXISTS observacion text;

CREATE OR REPLACE VIEW v_obsolescencia AS
SELECT id,
       hostname,
       juzgado,
       cod_act_pc,
       round(((CURRENT_DATE - fecha_bios))::numeric / 365.25, 1) AS antiguedad_anios,
       LEAST(100,
             CASE
                 WHEN fecha_bios IS NULL THEN 0
                 WHEN (CURRENT_DATE - fecha_bios) > 365 * 7 THEN 40
                 WHEN (CURRENT_DATE - fecha_bios) > 365 * 5 THEN 25
                 WHEN (CURRENT_DATE - fecha_bios) > 365 * 3 THEN 10
                 ELSE 0
             END
           + CASE WHEN tipo_disco = 'HDD' THEN 20 ELSE 0 END
           + CASE
                 WHEN tamano_memoria ILIKE '%MB%' THEN 15
                 WHEN COALESCE(NULLIF(regexp_replace(tamano_memoria, '\D', '', 'g'), '')::integer, 0) < 8 THEN 15
                 ELSE 0
             END
           + CASE WHEN tpm_version IS NOT NULL AND tpm_version NOT LIKE '2.0%' THEN 10 ELSE 0 END
           + CASE WHEN disco_salud IS NOT NULL AND disco_salud <> 'Healthy' THEN 30 ELSE 0 END
           + CASE WHEN disco_smart = 'FALLA' THEN 30 ELSE 0 END
           + CASE WHEN COALESCE(disco_desgaste_pct, 0) >= 80 THEN 20 ELSE 0 END
       ) AS score_obsolescencia
FROM equipos;
