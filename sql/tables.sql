-- CONNECT TO quantdb_test USER "quantdb-admin";


create table units(
-- load from either UO or protcur sources
id integer GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
-- full unit expression can be composed from prefix + unit
-- or some other unit expression, we won't handle it in here
-- we just want to be able to recover the unit expression
-- use the URI structure or substructure that we already use
-- in sparc to store the unit here, but expect to unpack it
-- as needed
--composed_unit varchar, -- not clear we need this right now
-- unit_expression varchar,
label text,
iri text unique
-- if we want to be abel to search over units we will need to enhance this
);

create table aspects(
-- can prepopulate many of these as well
id integer GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
label text,
description text,
iri text unique
);

create table class_measured(
-- the ontology class of the things being measured
id integer GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
label text,
description text,
iri text unique -- ontology_id,
--real_vs_symbolic, -- site vs roi, subject vs fiber/fascicle
--input_type,
);

CREATE TYPE instance_measured_type AS ENUM (
'sds', -- measurement or derived measure applying to a subject or sample
'below-sds', -- something below the sds ontology level, e.g. fibers, fascicles
'lifted-type' -- something below the sds ontology level but lifted, e.g. a gene id implying the rna transcribed for that gene that was extracted from/isolated form in a specific sample inevitably along with the rna for other genes as well
);

create table instance_measured(
id integer GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
-- the exact instance measured, e.g. for fibers it will be the fiber id
-- in a single section, and then also possibly unified later using their
-- common fiber tracking naming algorithm
local_identifier text, -- in spreadsheet mapping for the thing, could populate this automatically if we have a way to identify primary keys
specimen_id text unique, -- needs to be fully qualified with the dataset id i.e. from the ttl file
entity_id text unique, -- sub- sam- -- could be iri from ttl file?
entity_type instance_measured_type -- gene is a type level that implies "it is the expression of this gene in this context" where the context is implicit
--file_row_thing integer,
-- could could have the gene id or similar, multiple levels of context
);

--create table field_mapping(
-- not needed
-- mapping between the raw columns and the curated descriptors
-- what happens if a csv file changes?
-- TODO do we really want this fully normalized
--field,
--quant_desc,
--);


CREATE TYPE quant_shape AS ENUM (
'scalar'
);

CREATE TYPE quant_agg_type AS ENUM (
'instance',
'function',
'summary',
'mean',
'media',
'mode',
'sum'
);

create table quant_descriptors(
id integer GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
shape quant_shape NOT NULL DEFAULT 'scalar', -- do we handle arrays and matricies here, like linkml ndarray issue, some double values e.g. for elipses TODO can we use shape to dispatch to appropriate tables or do we have a values table
unit integer references units(id),  -- mm FK to units
aspect integer references aspects(id),  -- distance, diameter, width
is_measuring integer references class_measured(id), -- class_measured -- points to class_measured measureable_thing -- subject, mouse, sample, cell, neuron, site, electrode, roi, fiber, fasicle -- should be at a higher level, a type of thing, not instances
label text,
description text,
aggregation_type quant_agg_type NOT NULL DEFAULT 'instance', -- FIXME this impaces is_measuring as well
-- TODO if there is anything other than 'instance' in aggregation_type then we would expect
-- the measured_instance to point to a population of instance
curator_note text, -- particularly re: mapping
UNIQUE (unit, aspect, is_measuring, shape, aggregation_type)
);

CREATE TYPE prov_type AS ENUM (
'external-field', -- e.g. from SPARC data file
'internal computation' -- e.g. a complex select statement
);

create table provenance(
-- 
id integer GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
type prov_type, -- this control the interpretation of the field source
field_name text,
field_source text, -- file path ??? pennsieve package id + dataset id
-- XXX field source being file path implies sds entity id
quant_desc integer -- quant desc has to be entered first
);
-- if we want to use this to describe internal computations
-- field_name is the defined column name that the query returns
-- field_source is a query over quant_values or some join including it
-- quant_desc is the quant descriptor that is the output

/*
create table interal_computation(
id,
query,
resulting_value,
resulting_units,
);
*/

-- two processes
-- 1 mapping of tabular schema "precuration" initially just in inserts.sql
-- 2 ingest
-- during mapping there are cases where we will need to map columns
-- to input instance metadata in addition to quant_values, specifically
-- for gene ids, this is context living inside vs outside the source file

-- how to deal with gene expression levels, don't really want a descriptor per gene

-- what are measured instances
-- mouse that has subject id
-- gene expression from a sample where there are 23k values
-- fiber diameter identified in one section vs across sections (becomes gene)

create table quant_values( -- atomic scalar values
id integer GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
--units varchar NOT NULL,
--aspect varchar NOT NULL, -- XXX vs metric
--input varchar NOT NULL,
--input_type , -- real or symbolic, site or roi etc.
--input_or_symbolic , --
value numeric NOT NULL, -- FIXME might be an array or something? mostly present
quant_desc integer references quant_descriptors(id),  -- quant_desciptors id
prov integer references provenance(id), -- external_fields id --provenance
measured_instance integer references instance_measured(id), -- instance_measured id -- links simliar measures on the same input (row)
orig_value varchar,
orig_units varchar,
-- FIXME TODO may also need original_type if such information was tracked
value_blob jsonb NOT NULL -- a full json represntation that may have weird shapes
-- UNIQUE (quant_desc, prov, measured_instance), -- FIXME issues with repeated measures? issues with values
);
