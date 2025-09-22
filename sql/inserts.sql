/*
inserts for various curation flows
*/

-- begin from test.sql

INSERT INTO descriptors_inst (iri, label) VALUES -- NOTE TO SELF class measured is where we handle hierarchical resolution we don't do that for categorical values right now which is why we have the complexity in this table
('https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/sds/participant', 'participant'),
('https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/sds/specimen', 'specimen'),
('https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/sds/subject', 'subject'),  -- XXX now dragged up to instance_type
('https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/sds/sample', 'sample'),  -- XXX now dragged up to instance_type
('https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/sds/site', 'site'),
('https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/sds/performance', 'performance'),

-- FIXME ncbitax obvs, with subject now at type level we can include the species taxononmy here instead of in controlled terms
('https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/human', 'human'),
('https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/rat', 'rat'),
('https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/mouse', 'mouse'),
('https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/pig', 'pig'),
('https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/dog', 'dog'),
('https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/cat', 'cat'),
('https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/ferret', 'ferret'),

--('https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/virtual', 'virtual'), -- a data signature of a real thing (don't do it this way)

('https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/nerve', 'nerve'), -- nerve or branch but really just nerve or part of nerve
('https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/nerve/volume', 'nerve-volume'), -- aka
('https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/nerve/cross-section', 'nerve-cross-section'), -- an atomic section wrt the data
--('https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/nerve-segment', 'nerve-segment'), -- reva ft unit XXX do not use equiv to volume
--('https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/segment/cross-section', 'segment-cross-section'), -- single z plane, TODO do we need a data perspective name for these, e.g. image-z-stack-plane 3d-volume-plane

('https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/cell', 'cell'),
('https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/neuron', 'neuron'),
('https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/soma', 'soma'),
('https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/axon', 'axon'),
('https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/dendrite', 'dendrite'),

('https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/fascicle', 'fascicle'),
('https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/fiber', 'fiber'),
('https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/tissue', 'tissue'),

('https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/fascicle/cross-section', 'fascicle-cross-section'),
('https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/fiber/cross-section', 'fiber-cross-section'),
('https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/tissue/cross-section', 'tissue-cross-section'),

('https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/fascicle/volume', 'fascicle-volume'),
('https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/fiber/volume', 'fiber-volume'), -- FIXME axon ??
('https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/tissue/volume', 'tissue-volume'), -- this is the class we probably use for uct

--('https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/', ''),
--('https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/', ''),

('https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/thing', 'class thing')
;

INSERT INTO class_parent (id, parent) VALUES
-- TODO populate from subClassOf query from sparc-methods.ttl
-- FIXME also need to map to thing in cases where missing?
(desc_inst_from_label('specimen'),               desc_inst_from_label('participant')),
(desc_inst_from_label('subject'),                desc_inst_from_label('specimen')),
(desc_inst_from_label('sample'),                 desc_inst_from_label('specimen')), -- FIXME TODO do we have multi-parent for samples with types?
/*
Here is a conundrum for you.
nerve-cross-sections technically nerve-volumes with unit thickness (usually pixels)
which means that they are almost always digitized as a plane one dimension lower
however if i make nerve-volume a subClassOf volume then nerve-cross-section will
be a subClassOf both volume and area ... which I guess is ok actually ... because
the implication is clear, in 3d it has unit volume on one axis ... that has a nice
interpretation for cross sectional area ... as expected given the naming
*/
(desc_inst_from_label('nerve-volume'),           desc_inst_from_label('nerve')),
(desc_inst_from_label('nerve-cross-section'),    desc_inst_from_label('nerve-volume')),
(desc_inst_from_label('fascicle-volume'),        desc_inst_from_label('fascicle')),
(desc_inst_from_label('fascicle-cross-section'), desc_inst_from_label('fascicle-volume')),
(desc_inst_from_label('fiber-volume'),           desc_inst_from_label('fiber')),
(desc_inst_from_label('fiber-cross-section'),    desc_inst_from_label('fiber-volume'))
--(desc_inst_from_label(''),                       desc_inst_from_label('')),

;

INSERT INTO controlled_terms (iri, label) VALUES
('https://uri.interlex.org/tgbugs/uris/readable/quantdb/controlled/hack-associate-some-value', 'hack-associate-some-value'),
('https://uri.interlex.org/tgbugs/uris/readable/quantdb/controlled/fascicleStainType/chat', 'chat'),
('https://uri.interlex.org/tgbugs/uris/readable/quantdb/controlled/fascicleStainType/myelin', 'myelin'),
('https://uri.interlex.org/tgbugs/uris/readable/quantdb/controlled/fascicleStainType/neurofilament', 'neurofilament'),

('http://purl.obolibrary.org/obo/UBERON_0001021', 'nerve'),

('https://uri.interlex.org/tgbugs/uris/readable/quantdb/controlled/microct', 'microct'),

--('https://uri.interlex.org/tgbugs/uris/readable/quantdb/controlled/', ''),
('https://uri.interlex.org/tgbugs/uris/readable/quantdb/controlled/thing', 'controlled thing')
;

INSERT INTO descriptors_cat (label, domain, range) VALUES

-- these are examples that probably should not be used on real data because they are too
-- granular to be useful without the ability to traverse in the hierarchy
('fasciclePositiveStainType', desc_inst_from_label('fascicle-volume'),  'controlled'),
('fasciclePositiveStainType', desc_inst_from_label('fascicle-cross-section'),  'controlled'),

('fascicleNegativeStainType', desc_inst_from_label('fascicle-volume'),  'controlled'),
('fascicleNegativeStainType', desc_inst_from_label('fascicle-cross-section'),  'controlled'),

('positiveStainType', NULL, 'controlled'), -- this is a more practical approach
('hasDataAboutItModality', NULL, 'controlled'),
('hasAnatomicalTag', NULL, 'controlled'),
('hasAssociatedObject', NULL, 'controlled'), -- hasObjectAboutIt isn't used here because that predicate expects the rdf object to be the pointer to the data object (uuid), there is surely a clearer way to do this, e.g. not bottom but maybe just hackProperty or something but we probably want it to be, what we would actually want is probably the 'top' object property, but we don't have that

('bottom', NULL, 'controlled') -- XXX reminder: this one should never be used because it relates no individuals
;

INSERT INTO aspects (iri, label) VALUES
-- RULING distance is more fundamental, however it is literally definitional
-- unless it is being derived from some other quantity such as c
-- this is becuase you have to pick two specific points in order to define length
-- while distance is abstract and can unitized in countless ways (i.e. based on
-- which two points you pick)

('http://uri.interlex.org/tgbugs/uris/readable/aspect/count', 'count'),

('http://uri.interlex.org/tgbugs/uris/readable/aspect/distance', 'distance'),

--('http://uri.interlex.org/tgbugs/uris/readable/aspect/distance-via-reva-ft-sample-id-raw', 'distance-via-reva-ft-sample-id-raw'),

-- have a version independent aspect that can be used to pull back all related aspects
('http://uri.interlex.org/tgbugs/uris/readable/aspect/distance-vagus-normalized', 'distance-vagus-normalized'),
('http://uri.interlex.org/tgbugs/uris/readable/aspect/distance-via-vagus-level-normalized', 'distance-via-vagus-level-normalized'),
('http://uri.interlex.org/tgbugs/uris/readable/aspect/distance-via-vagus-level-normalized-v1', 'distance-via-vagus-level-normalized-v1'),

('http://uri.interlex.org/tgbugs/uris/readable/aspect/distance-via-reva-ft-sample-id-normalized', 'distance-via-reva-ft-sample-id-normalized'),
('http://uri.interlex.org/tgbugs/uris/readable/aspect/distance-via-reva-ft-sample-id-normalized-v1', 'distance-via-reva-ft-sample-id-normalized-v1'),
('http://uri.interlex.org/tgbugs/uris/readable/aspect/distance-via-reva-ft-sample-id-normalized-v2', 'distance-via-reva-ft-sample-id-normalized-v2'),

('http://uri.interlex.org/tgbugs/uris/readable/aspect/length', 'length'),
('http://uri.interlex.org/tgbugs/uris/readable/aspect/diameter', 'diameter'),
('http://uri.interlex.org/tgbugs/uris/readable/aspect/diameter-orthogonal-to-anterior-posterior-axis', 'diameter-orthogonal-to-anterior-posterior-axis'),
('http://uri.interlex.org/tgbugs/uris/readable/aspect/length-parallel-to-anterior-posterior-axis', 'length-parallel-to-anterior-posterior-axis')
-- ('http://uri.interlex.org/tgbugs/uris/readable/aspect/', ''),
;

INSERT INTO aspect_parent (id, parent) VALUES
(aspect_from_label('length'), aspect_from_label('distance')),
--(aspect_from_label('distance-via-reva-ft-sample-id-raw'), aspect_from_label('distance')),
(aspect_from_label('distance-vagus-normalized'), aspect_from_label('distance')),
(aspect_from_label('distance-via-reva-ft-sample-id-normalized'), aspect_from_label('distance-vagus-normalized')),
-- (aspect_from_label('distance-via-reva-ft-sample-id-normalized'), aspect_from_label('distance')),  -- TODO delete ? or ok ? might break stuff?
(aspect_from_label('distance-via-reva-ft-sample-id-normalized-v1'), aspect_from_label('distance-via-reva-ft-sample-id-normalized')),
(aspect_from_label('distance-via-reva-ft-sample-id-normalized-v2'), aspect_from_label('distance-via-reva-ft-sample-id-normalized')),

(aspect_from_label('distance-via-vagus-level-normalized'), aspect_from_label('distance-vagus-normalized')),
(aspect_from_label('distance-via-vagus-level-normalized-v1'), aspect_from_label('distance-via-vagus-level-normalized')),

(aspect_from_label('diameter'), aspect_from_label('length')),
(aspect_from_label('diameter-orthogonal-to-anterior-posterior-axis'), aspect_from_label('diameter')),
(aspect_from_label('length-parallel-to-anterior-posterior-axis'), aspect_from_label('length'))
--(aspect_from_label(), aspect_from_label()),
;

INSERT INTO units (iri, label) VALUES
-- obvious we need synonyms
-- TODO need to decide on naming convention for units becuase label is likely to be the primary interface to the table
('http://uri.interlex.org/tgbugs/uris/readable/aspect/unit/unitless', 'unitless'), --  we need explicit unitless so we can distinguish cases where there was a partial ingest

('http://uri.interlex.org/tgbugs/uris/readable/aspect/unit/micrometer', 'um'),
('http://uri.interlex.org/tgbugs/uris/readable/aspect/unit/meter', 'm')
-- ('http://uri.interlex.org/tgbugs/uris/readable/aspect/unit/', ''),
;


INSERT INTO descriptors_quant (label, domain, aspect, unit, aggregation_type) VALUES
-- lack of support for hierarchical queries over aspects is a killer here, and also for classes

(
'count', -- TODO 'count of domain-thing' vs 'count of range-thing in domain-thing'
NULL,
aspect_from_label('count'),
unit_from_label('unitless'),  -- FIXME we MIGHT be able to have another column that points to desc_inst for members of population? TODO needs more design and examples
-- it does seem that the quantitative descriptor sits at a nice place in the data model to allow for composition of domain/range scope/thing but then we would need to be able to distinguish between qd types that are scoped entirely by their subject (length) vs more than 1 (distance) vs count-of-sheep-in-field-at-time
'instance' -- FIXME population probably
),

('thing object uuid ratio', -- multiple objects means the entity will show up at multiple places, OR pick min or something ...
/*
FIXME technically in order to insert these we need to have an instance AND at least one object
we don't want to create a bunch of file object instances though, the first time that we actually know that an
object id has data about an instance id is when it is entered into values_quant or values_cat
which means that if we don't want the uuid ratio process to create spurious entities then we can only
run this on whole files that map directly subject or sample level, which is already what we assume
for the reva ft vagus segment microct case
another way to frame the issue is that if you have multiple files with data that maps to slightly different
parts of an instance then you probably want/need slightly different instance ids to map because the data model
assumes that the data inside individual records (sometimes records are whole files) correspond to a single instance
cases of multiple reva ft uct images for single sample segment are an example of the issue
i.e. we may need sites, otherwise files "about" the same thing are going to teleport and the location
of an object in uuid space will change over time ... ah well, that is the issue with this coordinate system
which is that objects are located in n dimensional uuid space, not just 1d uuid space, and n changes over
time, so either you take the norm or you take the min across all axes but that has to be done after the fact

values_quant or values_cat ? but that doesn't work because of the circularity, the problem is that we already
instance ids for this to work
*/
NULL, -- desc_inst_from_label('file'), -- FIXME VS desc_inst_from_label('class thing'),
aspect_from_label('distance-object-uuid-ratio'), -- yes this is an abstract distance in UUID space between zero and max int 128
-- curator_note: non-locality of mapping to uuid space is fun
NULL,
'instance'
),

('thing min object uuid ratio',
/*
FIXME TODO practical issue: we assume objects are immutable, so thing object uuid ratio is ok
because we create a obj_desc_quant for it for it that references the non-min version of
this and will always be static, however min could change every time ... actually ... we are ok
right now because there are no unique constraints on enabled right now, but as soon as we do
enable them we are going to be in trouble and if we don't enable them then we will have multiple
min values in the database, from a conceptual standpoint this means that internal objects have to
be append only as well, they don't have to be immutable, but any additions to them can't result in
a change to an existing record, this means that when we recompute the min we have to issue a new
internal object id, but we might be able to be smart about and have e.g. one uuid for the 1st
min addition, 2nd, etc. essentially pretending that there is an append only no duplicates file
that tracks the min as things update ... this is ... not an ideal solution, and it also shows that
there will be issue if there are multiple versions of the same measures ... this is already
discussed in the context of aspects when dealing with multiple very similar columns
either you factor out performance, or the analysis is different so the results may share a superclass
but have to be distinct in their aspect name or something
*/
NULL,
aspect_from_label('distance-object-uuid-ratio'),
unit_from_label('unitless'),
'min'
),

/*
('reva ft sample anatomical location distance index raw',
desc_inst_from_label('nerve-volume'),
aspect_from_label('distance-via-reva-ft-sample-id-raw'),
unit_from_label('unitless'),
'instance'),
*/

('reva ft sample anatomical location distance index normalized v1',
desc_inst_from_label('nerve'),
aspect_from_label('distance-via-reva-ft-sample-id-normalized-v1'),
unit_from_label('unitless'),
'instance'),  -- FIXME this isn't really instance, it is normalized across a whole population, which we might want to indicate here

('reva ft sample anatomical location distance index normalized v1 min',
desc_inst_from_label('nerve'),
aspect_from_label('distance-via-reva-ft-sample-id-normalized-v1'),
unit_from_label('unitless'),
'min'),

('reva ft sample anatomical location distance index normalized v1 max',
desc_inst_from_label('nerve'),
aspect_from_label('distance-via-reva-ft-sample-id-normalized-v1'),
unit_from_label('unitless'),
'max'),

('reva ft sample anatomical location distance index normalized v2',
desc_inst_from_label('nerve'),
aspect_from_label('distance-via-reva-ft-sample-id-normalized-v2'),
unit_from_label('unitless'),
'instance'),  -- FIXME this isn't really instance, it is normalized across a whole population, which we might want to indicate here

('reva ft sample anatomical location distance index normalized v2 min',
desc_inst_from_label('nerve'),
aspect_from_label('distance-via-reva-ft-sample-id-normalized-v2'),
unit_from_label('unitless'),
'min'),

('reva ft sample anatomical location distance index normalized v2 max',
desc_inst_from_label('nerve'),
aspect_from_label('distance-via-reva-ft-sample-id-normalized-v2'),
unit_from_label('unitless'),
'max'),

-- for 55c5

('vagus level anatomical location distance index normalized v1',
desc_inst_from_label('nerve'), -- FIXME make sure this works as expected
aspect_from_label('distance-via-vagus-level-normalized-v1'),
unit_from_label('unitless'),
'instance'),

('vagus level anatomical location distance index normalized v1 min',
desc_inst_from_label('nerve'),
aspect_from_label('distance-via-vagus-level-normalized-v1'),
unit_from_label('unitless'),
'min'),

('vagus level anatomical location distance index normalized v1 max',
desc_inst_from_label('nerve'),
aspect_from_label('distance-via-vagus-level-normalized-v1'),
unit_from_label('unitless'),
'max'),

-- general

('nerve cross section diameter um',
desc_inst_from_label('nerve-cross-section'),
aspect_from_label('diameter'),
unit_from_label('um'),
'instance'),

('fascicle cross section diameter um',
desc_inst_from_label('fascicle-cross-section'),
aspect_from_label('diameter'),
unit_from_label('um'),
'instance'),

('fascicle cross section diameter um min',
desc_inst_from_label('fascicle-cross-section'),
aspect_from_label('diameter'),
unit_from_label('um'),
'min'), -- FIXME ... not really an agg type ...

('fascicle cross section diameter um max',
desc_inst_from_label('fascicle-cross-section'),
aspect_from_label('diameter'),
unit_from_label('um'),
'max'), -- FIXME ... not really an agg type ...

('fascicle volume diameter orth-ap-axis um minimum',
desc_inst_from_label('fascicle-volume'),
aspect_from_label('diameter-orthogonal-to-anterior-posterior-axis'), -- and here we see the problem
unit_from_label('um'),
'min'),

('fascicle volume length parallel-to-ap-axis um',
desc_inst_from_label('fascicle-volume'),
aspect_from_label('length-parallel-to-anterior-posterior-axis'),
unit_from_label('um'),
'instance')

;

INSERT INTO addresses (addr_type, addr_field) VALUES
('constant', NULL),
('constant', 'literally this value right here'),
--('curator', 'tgbugs'),
('tabular-header', 'id'),
('tabular-header', 'stain'),
('tabular-header', 'diameter'),
('tabular-header', 'diameter-min'),
('tabular-header', 'diameter-max'),

('tabular-header', 'id_sub'),
('tabular-header', 'id_sam'),
('tabular-header', 'species'),
('tabular-header', 'sample_type'),
('tabular-header', 'modality'),

('tabular-header', 'NFasc'),
('tabular-header', 'dNerve_um'),
('tabular-header', 'laterality'),
('tabular-header', 'level'),
('json-path-with-types', '#/#int/dFasc_um'),
('json-path-with-types', '#/#int/dFasc_um/#int'),

('json-path-with-types', '#/curation-export/subjects/#int/id_sub'), -- [i for i, s in enumerate(subjects) if s['id_sub'] == id_sub][0]
('json-path-with-types', '#/curation-export/subjects/#int/species'),
('json-path-with-types', '#/curation-export/samples/#int/id_sam'),
('json-path-with-types', '#/curation-export/samples/#int/sample_type'),
('json-path-with-types', '#/curation-export/samples/#int/raw_anat_index'),
('json-path-with-types', '#/curation-export/samples/#int/norm_anat_index'),
('json-path-with-types', '#/curation-export/manifest/#int/modality'),  -- FIXME not real
('json-path-with-types', '#/combined/{object_uuid}/external/modality'),  -- FIXME not real

('json-path-with-types', '#/path-metadata/data/#int/dataset_relative_path'),
('json-path-with-types', '#/path-metadata/data/#int/dataset_relative_path#derive-modality'),
('json-path-with-types', '#/path-metadata/data/#int/dataset_relative_path#derive-raw-anat-index'),
('json-path-with-types', '#/path-metadata/data/#int/dataset_relative_path#derive-norm-anat-index-v1'),
('json-path-with-types', '#/path-metadata/data/#int/dataset_relative_path#derive-norm-anat-index-v1-min'),
('json-path-with-types', '#/path-metadata/data/#int/dataset_relative_path#derive-norm-anat-index-v1-max'),
('json-path-with-types', '#/path-metadata/data/#int/dataset_relative_path#derive-norm-anat-index-v2'),
('json-path-with-types', '#/path-metadata/data/#int/dataset_relative_path#derive-norm-anat-index-v2-min'),
('json-path-with-types', '#/path-metadata/data/#int/dataset_relative_path#derive-norm-anat-index-v2-max'),
('json-path-with-types', '#/path-metadata/data/#int/dataset_relative_path#derive-subject-id'),
('json-path-with-types', '#/path-metadata/data/#int/dataset_relative_path#derive-sample-id'),

('json-path-with-types', '#/local/tom-made-it-up/species'),
('json-path-with-types', '#/local/tom-made-it-up/sample_type')

--('image-axis-index', 'x'), -- TODO we aren't reading values out here, we are using implicit values to assign an id
--(,)
;

INSERT INTO addresses (addr_type, addr_field, value_type) VALUES
('tabular-header', 'stain', 'multi'),
('tabular-header', 'stain-negative', 'multi')
--(,,)
;

-- end from test.sql

-- f006
INSERT INTO addresses (addr_type, addr_field) VALUES
('record-index', NULL),
-- fascicles
('tabular-header', 'fascicle'),
('tabular-header', 'area'),
('tabular-header', 'longest_diameter'),
('tabular-header', 'shortest_diameter'),
('tabular-header', 'eff_diam'),
('tabular-header', 'c_estimate_nav'),
('tabular-header', 'c_estimate_nf'),
('tabular-header', 'nfibers_w_c_estimate_nav'),
('tabular-header', 'nfibers_w_c_estimate_nf'),
('tabular-header', 'nfibers_all'),
('tabular-header', 'n_a_alpha'),
('tabular-header', 'n_a_beta'),
('tabular-header', 'n_a_gamma'),
('tabular-header', 'n_a_delta'),
('tabular-header', 'n_b'),
('tabular-header', 'n_unmyel_nf'),
('tabular-header', 'n_nav'),
('tabular-header', 'n_chat'),
('tabular-header', 'n_myelinated'),
('tabular-header', 'area_a_alpha'),
('tabular-header', 'area_a_beta'),
('tabular-header', 'area_a_gamma'),
('tabular-header', 'area_a_delta'),
('tabular-header', 'area_b'),
('tabular-header', 'area_unmyel_nf'),
('tabular-header', 'area_nav'),
('tabular-header', 'area_chat'),
('tabular-header', 'area_myelinated'),
('tabular-header', 'crop_x_start'),
('tabular-header', 'crop_x_stop'),
('tabular-header', 'crop_y_start'),
('tabular-header', 'crop_y_stop'),
('tabular-header', 'chat_available'),
('tabular-header', 'nav_available'),
('tabular-header', 'th_available'),
('tabular-header', 'x_pix'),
('tabular-header', 'y_pix'),
('tabular-header', 'x_um'),
('tabular-header', 'y_um'),
('tabular-header', 'x_cent'),
('tabular-header', 'y_cent'),
('tabular-header', 'rho'),
('tabular-header', 'rho_pix'),
('tabular-header', 'phi'),
('tabular-header', 'epi_dist'),
('tabular-header', 'epi_dist_inv'),
('tabular-header', 'nerve_based_area'),
('tabular-header', 'nerve_based_perimeter'),
('tabular-header', 'nerve_based_eff_diam'),
('tabular-header', 'perinerium_vertices'),
('tabular-header', 'perinerium_vertices_px'),
('tabular-header', 'nerve_based_shortest_diameter'),
('tabular-header', 'hull_contrs'),
('tabular-header', 'hull_contr_areas'),

-- fibers
('tabular-header', 'a_alpha'),
('tabular-header', 'a_beta'),
('tabular-header', 'a_delta'),
('tabular-header', 'a_gamma'),
('tabular-header', 'b'),
--('tabular-header', 'c_estimate_nav'),
('tabular-header', 'c_estimate_nav_frac'),
--('tabular-header', 'c_estimate_nf'),
('tabular-header', 'c_estimate_nf_frac'),
('tabular-header', 'chat'),
--('tabular-header', 'chat_available'),
('tabular-header', 'eff_fib_diam'),
('tabular-header', 'eff_fib_diam_w_myel'),
--('tabular-header', 'fascicle'),
('tabular-header', 'fiber_area'),
('tabular-header', 'fiber_area_pix'),
('tabular-header', 'hull_vertices'),
('tabular-header', 'hull_vertices_w_myel'),
--('tabular-header', 'longest_diameter'),
('tabular-header', 'longest_diameter_w_myel'),
('tabular-header', 'max_myelin_thickness'),
('tabular-header', 'median_myelin_thickness'),
('tabular-header', 'myelin_area'),
('tabular-header', 'myelin_area_pix'),
('tabular-header', 'myelinated'),
('tabular-header', 'nav'),
--('tabular-header', 'nav_available'),
('tabular-header', 'peri_dist'),
('tabular-header', 'perimeter'),
--('tabular-header', 'phi'),
--('tabular-header', 'rho'),
--('tabular-header', 'rho_pix'),
--('tabular-header', 'shortest_diameter'),
('tabular-header', 'shortest_diameter_w_myel'),
--('tabular-header', 'th_available'),
('tabular-header', 'th_myelin_p'),
('tabular-header', 'th_not_nf'),
('tabular-header', 'th_overlap_p'),
('tabular-header', 'unmyel_nf'),
('tabular-header', 'x'),
--('tabular-header', 'x_pix'),
('tabular-header', 'x_pix_lvl'),
('tabular-header', 'y'),
--('tabular-header', 'y_pix'),
('tabular-header', 'y_pix_lvl'),

-- sds metadata sources
('tabular-header', 'subject_id'),
('tabular-header', 'sample_id'),
('tabular-header', 'site_id'),
--('tabular-header', 'species'),
--('tabular-header', 'sample_type'),
('tabular-header', 'site_type'),

-- vagus scaffold
('tabular-header', 'max_coord'),
('tabular-header', 'min_coord'),
('tabular-header', 'rotation_1'),
('tabular-header', 'rotation_2'),
('tabular-header', 'rotation_3'),
('tabular-header', 'scale'),
('tabular-header', 'translation_x'),
('tabular-header', 'translation_y'),
('tabular-header', 'translation_z'),

-- curation export paths
('json-path-with-types', '#/curation-export/subjects/#int/subject_id'),
('json-path-with-types', '#/curation-export/subjects/#int/species#translate_species'),
('json-path-with-types', '#/curation-export/samples/#int/sample_id'),
('json-path-with-types', '#/curation-export/samples/#int/sample_type#translate_sample_type'),
('json-path-with-types', '#/curation-export/sites/#int/site_id'),
('json-path-with-types', '#/curation-export/sites/#int/sites_type#translate_sites_type')

;

INSERT INTO units (iri, label) VALUES
('http://uri.interlex.org/tgbugs/uris/readable/aspect/unit/um2', 'um2'),
('http://uri.interlex.org/tgbugs/uris/readable/aspect/unit/degree', 'degree'), -- REMINDER for ontology ids we do not use plurals
-- XXX FIXME pixels these are count-of-thing that likely need to be handled separately that is frogs, sheep in field etc. to avoid mirroring hierarchy
('http://uri.interlex.org/tgbugs/uris/readable/aspect/unit/pixel', 'pixel'),
('http://uri.interlex.org/tgbugs/uris/readable/aspect/unit/pixel-9um', 'pixel-9um'),
('http://uri.interlex.org/tgbugs/uris/readable/aspect/unit/pixel-11um', 'pixel-11um') -- FIXME might be 11.something
;

INSERT INTO aspects (iri, label) VALUES
-- technically position is a vector of distances from a defined starting point or in a defined coordinate system

('http://uri.interlex.org/tgbugs/uris/readable/aspect/identifier/instance', 'identifier-instance'),

('http://uri.interlex.org/tgbugs/uris/readable/aspect/position', 'position'), -- XXX this is always relative to something that needs to be specified
('http://uri.interlex.org/tgbugs/uris/readable/aspect/centroid', 'centroid'),
-- distance
('http://uri.interlex.org/tgbugs/uris/readable/aspect/distance-along-axis', 'distance-along-axis'),
('http://uri.interlex.org/tgbugs/uris/readable/aspect/translation', 'translation'),
('http://uri.interlex.org/tgbugs/uris/readable/aspect/translation-along-axis', 'translation-along-axis'), -- FIXME TODO scalar components of vectors are not vectors ... they have some other relationship, not subClassOf, probably we want translation -> translation-scalar and translation-vector
('http://uri.interlex.org/tgbugs/uris/readable/aspect/translation-x', 'translation-x'),
('http://uri.interlex.org/tgbugs/uris/readable/aspect/translation-y', 'translation-y'),
('http://uri.interlex.org/tgbugs/uris/readable/aspect/translation-z', 'translation-z'),

('http://uri.interlex.org/tgbugs/uris/readable/aspect/centroid-x', 'centroid-x'), -- FIXME technically this is part of a cenroid aspects but vectors ...
('http://uri.interlex.org/tgbugs/uris/readable/aspect/centroid-y', 'centroid-y'), -- FIXME technically this is part of a cenroid aspects but vectors ...
('http://uri.interlex.org/tgbugs/uris/readable/aspect/radius', 'radius'),
('http://uri.interlex.org/tgbugs/uris/readable/aspect/radius/from/parent/centroid', 'radius-from-parent-centroid'), -- from-parent-instance-cendroid but instance is implied
('http://uri.interlex.org/tgbugs/uris/readable/aspect/perimeter', 'perimeter'),

('http://uri.interlex.org/tgbugs/uris/readable/aspect/distance-via-abi-vagus-scaffold', 'distance-via-abi-vagus-scaffold'),
('http://uri.interlex.org/tgbugs/uris/readable/aspect/distance-via-abi-vagus-scaffold-v1', 'distance-via-abi-vagus-scaffold-v1'),

('http://uri.interlex.org/tgbugs/uris/readable/aspect/area', 'area'),

('http://uri.interlex.org/tgbugs/uris/readable/aspect/volume', 'volume'),

('http://uri.interlex.org/tgbugs/uris/readable/aspect/angle', 'angle'),
('http://uri.interlex.org/tgbugs/uris/readable/aspect/angle/from/parent/centroid', 'angle-from-parent-centroid'), -- FIXME -from- implies we need context for these

('http://uri.interlex.org/tgbugs/uris/readable/aspect/rotation', 'rotation'),
('http://uri.interlex.org/tgbugs/uris/readable/aspect/rotation-around-axis', 'rotation-around-axis'),
('http://uri.interlex.org/tgbugs/uris/readable/aspect/rotation-x', 'rotation-x'),
('http://uri.interlex.org/tgbugs/uris/readable/aspect/rotation-y', 'rotation-y'),
('http://uri.interlex.org/tgbugs/uris/readable/aspect/rotation-z', 'rotation-z'),

-- placeholder hierarchy until i can update desc quant to allow a second desc_inst

('http://uri.interlex.org/tgbugs/uris/readable/aspect/count/fiber', 'count-fiber'),
('http://uri.interlex.org/tgbugs/uris/readable/aspect/count/fiber/a', 'count-fiber-a'),
('http://uri.interlex.org/tgbugs/uris/readable/aspect/count/fiber/a/alpha', 'count-fiber-a-alpha'),
('http://uri.interlex.org/tgbugs/uris/readable/aspect/count/fiber/a/beta', 'count-fiber-a-beta'),
('http://uri.interlex.org/tgbugs/uris/readable/aspect/count/fiber/a/gamma', 'count-fiber-a-gamma'),
('http://uri.interlex.org/tgbugs/uris/readable/aspect/count/fiber/a/delta', 'count-fiber-a-delta'),
('http://uri.interlex.org/tgbugs/uris/readable/aspect/count/fiber/b', 'count-fiber-b'),
('http://uri.interlex.org/tgbugs/uris/readable/aspect/count/fiber/c', 'count-fiber-c'),
('http://uri.interlex.org/tgbugs/uris/readable/aspect/count/fiber/myelinated', 'count-fiber-myelinated'),
('http://uri.interlex.org/tgbugs/uris/readable/aspect/count/fiber/unmyelinated', 'count-fiber-unmyelinated'),
('http://uri.interlex.org/tgbugs/uris/readable/aspect/count/fiber/chat', 'count-fiber-chat'),
('http://uri.interlex.org/tgbugs/uris/readable/aspect/count/fiber/nav', 'count-fiber-nav'),

('http://uri.interlex.org/tgbugs/uris/readable/aspect/area/fiber', 'area-fiber'),
('http://uri.interlex.org/tgbugs/uris/readable/aspect/area/fiber/a', 'area-fiber-a'),
('http://uri.interlex.org/tgbugs/uris/readable/aspect/area/fiber/a/alpha', 'area-fiber-a-alpha'),
('http://uri.interlex.org/tgbugs/uris/readable/aspect/area/fiber/a/beta', 'area-fiber-a-beta'),
('http://uri.interlex.org/tgbugs/uris/readable/aspect/area/fiber/a/gamma', 'area-fiber-a-gamma'),
('http://uri.interlex.org/tgbugs/uris/readable/aspect/area/fiber/a/delta', 'area-fiber-a-delta'),
('http://uri.interlex.org/tgbugs/uris/readable/aspect/area/fiber/b', 'area-fiber-b'),
('http://uri.interlex.org/tgbugs/uris/readable/aspect/area/fiber/c', 'area-fiber-c'),
('http://uri.interlex.org/tgbugs/uris/readable/aspect/area/fiber/myelinated', 'area-fiber-myelinated'),
('http://uri.interlex.org/tgbugs/uris/readable/aspect/area/fiber/unmyelinated', 'area-fiber-unmyelinated'),
('http://uri.interlex.org/tgbugs/uris/readable/aspect/area/fiber/chat', 'area-fiber-chat'),
('http://uri.interlex.org/tgbugs/uris/readable/aspect/area/fiber/nav', 'area-fiber-nav'),

-- duration

('http://uri.interlex.org/tgbugs/uris/readable/aspect/duration/duration', 'duration'),
('http://uri.interlex.org/tgbugs/uris/readable/aspect/duration/age', 'age'),
('http://uri.interlex.org/tgbugs/uris/readable/aspect/duration/age/since/birth', 'age-since-birth'),
('http://uri.interlex.org/tgbugs/uris/readable/aspect/duration/age/since/zygote', 'age-since-zygote'),
('http://uri.interlex.org/tgbugs/uris/readable/aspect/duration/age/since/naming', 'age-since-naming'),

-- time (duration since agreed upon reference points)
('http://uri.interlex.org/tgbugs/uris/readable/aspect/duration/since', 'time-system'), -- since epoch
('http://uri.interlex.org/tgbugs/uris/readable/aspect/duration/since/unix-epoch', 'unix-epoch'),
('http://uri.interlex.org/tgbugs/uris/readable/aspect/duration/since/common-era-iso', 'common-era-iso'), -- confusingly 0000-01-01 is January 1st 1 BCE, so BCE dates are negative (non-positive) iso dates |YYYY -1| which is horrible for notation
-- XXX things like date of birth are properly aspects of a particular type of event involving the subject ...

-- mass weight

('http://uri.interlex.org/tgbugs/uris/readable/aspect/mass', 'mass'),
('http://uri.interlex.org/tgbugs/uris/readable/aspect/weight', 'weight')

;

INSERT INTO aspect_parent (parent, id) VALUES
(aspect_from_label('distance'), aspect_from_label('radius')),
(aspect_from_label('distance'), aspect_from_label('perimeter')),
(aspect_from_label('radius'), aspect_from_label('radius-from-parent-centroid')),
(aspect_from_label('angle'), aspect_from_label('angle-from-parent-centroid')),
(aspect_from_label('angle'), aspect_from_label('rotation')),
(aspect_from_label('rotation'), aspect_from_label('rotation-around-axis')),
(aspect_from_label('rotation-around-axis'), aspect_from_label('rotation-x')),
(aspect_from_label('rotation-around-axis'), aspect_from_label('rotation-y')),
(aspect_from_label('rotation-around-axis'), aspect_from_label('rotation-z')),

(aspect_from_label('position'), aspect_from_label('centroid')),
(aspect_from_label('distance'), aspect_from_label('distance-along-axis')),
(aspect_from_label('distance-along-axis'), aspect_from_label('centroid-x')), -- technically correct but annoying to find due to needing partOf or similar
(aspect_from_label('distance-along-axis'), aspect_from_label('centroid-y')), -- and due to lacking vectors atm

(aspect_from_label('distance'), aspect_from_label('translation')),
(aspect_from_label('distance-along-axis'), aspect_from_label('translation-along-axis')),
(aspect_from_label('translation-along-axis'), aspect_from_label('translation-x')),
(aspect_from_label('translation-along-axis'), aspect_from_label('translation-y')),
(aspect_from_label('translation-along-axis'), aspect_from_label('translation-z')),

(aspect_from_label('distance-vagus-normalized'), aspect_from_label('distance-via-abi-vagus-scaffold')),
(aspect_from_label('distance-via-abi-vagus-scaffold'), aspect_from_label('distance-via-abi-vagus-scaffold-v1')),

-- XXX placeholders

(aspect_from_label('count'), aspect_from_label('count-fiber')),
(aspect_from_label('count-fiber'), aspect_from_label('count-fiber-a')),
(aspect_from_label('count-fiber-a'), aspect_from_label('count-fiber-a-alpha')),
(aspect_from_label('count-fiber-a'), aspect_from_label('count-fiber-a-beta')),
(aspect_from_label('count-fiber-a'), aspect_from_label('count-fiber-a-gamma')),
(aspect_from_label('count-fiber-a'), aspect_from_label('count-fiber-a-delta')),
(aspect_from_label('count-fiber'), aspect_from_label('count-fiber-b')),
(aspect_from_label('count-fiber'), aspect_from_label('count-fiber-c')),
(aspect_from_label('count-fiber'), aspect_from_label('count-fiber-myelinated')),
(aspect_from_label('count-fiber'), aspect_from_label('count-fiber-unmyelinated')),
(aspect_from_label('count-fiber'), aspect_from_label('count-fiber-chat')),
(aspect_from_label('count-fiber'), aspect_from_label('count-fiber-nav')),

(aspect_from_label('area'), aspect_from_label('area-fiber')),
(aspect_from_label('area-fiber'), aspect_from_label('area-fiber-a')),
(aspect_from_label('area-fiber-a'), aspect_from_label('area-fiber-a-alpha')),
(aspect_from_label('area-fiber-a'), aspect_from_label('area-fiber-a-beta')),
(aspect_from_label('area-fiber-a'), aspect_from_label('area-fiber-a-gamma')),
(aspect_from_label('area-fiber-a'), aspect_from_label('area-fiber-a-delta')),
(aspect_from_label('area-fiber'), aspect_from_label('area-fiber-b')),
(aspect_from_label('area-fiber'), aspect_from_label('area-fiber-c')),
(aspect_from_label('area-fiber'), aspect_from_label('area-fiber-myelinated')),
(aspect_from_label('area-fiber'), aspect_from_label('area-fiber-unmyelinated')),
(aspect_from_label('area-fiber'), aspect_from_label('area-fiber-chat')),
(aspect_from_label('area-fiber'), aspect_from_label('area-fiber-nav')),

-- time

(aspect_from_label('duration'), aspect_from_label('age')),
(aspect_from_label('duration'), aspect_from_label('time-system')),
(aspect_from_label('age'), aspect_from_label('age-since-birth')),
(aspect_from_label('age'), aspect_from_label('age-since-zygote')),
(aspect_from_label('age'), aspect_from_label('age-since-naming')),

(aspect_from_label('time-system'), aspect_from_label('unix-epoch')),
(aspect_from_label('time-system'), aspect_from_label('common-era-iso'))

--(aspect_from_label('parent'), aspect_from_label('child')),

;

INSERT INTO descriptors_quant (label, domain, aspect, unit, aggregation_type) VALUES

('fiber cross section area um2',
desc_inst_from_label('fiber-cross-section'),
aspect_from_label('area'),
unit_from_label('um2'),
'instance'),

('fiber cross section diameter um',
desc_inst_from_label('fiber-cross-section'),
aspect_from_label('diameter'),
unit_from_label('um'),
'instance'),

('fiber cross section diameter um min',
desc_inst_from_label('fiber-cross-section'),
aspect_from_label('diameter'),
unit_from_label('um'),
'min'),

('fiber cross section diameter um max',
desc_inst_from_label('fiber-cross-section'),
aspect_from_label('diameter'),
unit_from_label('um'),
'max'),

-- scaffold mapping

('distance-via-abi-vagus-scaffold-v1 max',
desc_inst_from_label('nerve'),
aspect_from_label('distance-via-abi-vagus-scaffold-v1'),
unit_from_label('unitless'),
'max'),

('distance-via-abi-vagus-scaffold-v1 min',
desc_inst_from_label('nerve'),
aspect_from_label('distance-via-abi-vagus-scaffold-v1'),
unit_from_label('unitless'),
'min'),

('rotation around axis x in degrees',
null,
aspect_from_label('rotation-around-axis-x'),
unit_from_label('degrees'),
'instance'),

('rotation around axis y in degrees',
null,
aspect_from_label('rotation-around-axis-y'),
unit_from_label('degrees'),
'instance'),

('rotation around axis z in degrees',
null,
aspect_from_label('rotation-around-axis-z'),
unit_from_label('degrees'),
'instance'),

('translation-x in um',
null,
aspect_from_label('translation-x'),
unit_from_label('um'),
'instance'),

('translation-y in um',
null,
aspect_from_label('translation-y'),
unit_from_label('um'),
'instance'),

('translation-z in um',
null,
aspect_from_label('translation-z'),
unit_from_label('um'),
'instance'),

('scale',
null,
aspect_from_label('scale'),
unit_from_label('unitless'),
'instance'),

-- aspect of type in context

/* -- this one is wrong i think
('fiber count in fascicle cross section',
desc_inst_from_label('fascicle-cross-section'),
aspect_from_label('count-fiber-nf'),
null,
'instance'),
*/

-- address: fascicle
-- XXX (is desc_inst or not actually quantitative but instead an identifer that also happens to be a quantity)

('fascicle cross section area um2', -- address: area
desc_inst_from_label('fascicle-cross-section'),
aspect_from_label('area'),
unit_from_label('um2'),
'instance'),
/*
('fascicle cross section diameter um max', -- address: longest_diameter
desc_inst_from_label('fascicle-cross-section'), -- also in test.sql
aspect_from_label('diameter'),
unit_from_label('um'),
'max'),
('fascicle cross section diameter um min', -- address: shortest_diameter
desc_inst_from_label('fascicle-cross-section'), -- also in test.sql
aspect_from_label('diameter'),
unit_from_label('um'),
'min'),
('fascicle cross section diameter um', -- address: eff_diam
desc_inst_from_label('fascicle-cross-section'), -- also in test.sql FIXME equivalent area circle diameter ...
aspect_from_label('diameter'),
unit_from_label('um'),
'instance'),
*/
('nav fiber count in fascicle cross section estimated', -- address: c_estimate_nav
desc_inst_from_label('fascicle-cross-section'),
aspect_from_label('count-fiber'),
null,
'summary'),
('fiber count in fascicle cross section estimated', -- address: c_estimate_nf
desc_inst_from_label('fascicle-cross-section'), -- FIXME not sure how to interpret this though ... also nf nerve fiber or neurofilament?
aspect_from_label('count-estimated-fiber'),
null,
'summary'),
-- address: nfibers_w_c_estimate_nav
-- address: nfibers_w_c_estimate_nf
('fiber count in fascicle cross section', -- address: nfibers_all
desc_inst_from_label('fascicle-cross-section'),
aspect_from_label('count-fiber'),
null,
'summary'),

-- fiber counts

('a fiber count in fascicle cross section',
desc_inst_from_label('fascicle-cross-section'),
aspect_from_label('count-fiber-a'),
null,
'summary'),
('alpha a fiber count in fascicle cross section', -- address: n_a_alpha
desc_inst_from_label('fascicle-cross-section'),
aspect_from_label('count-fiber-a-alpha'),
null,
'summary'),
('beta a fiber count in fascicle cross section', -- address: n_a_beta
desc_inst_from_label('fascicle-cross-section'),
aspect_from_label('count-fiber-a-beta'),
null,
'summary'),
('gamma a fiber count in fascicle cross section', -- address: n_a_gamma
desc_inst_from_label('fascicle-cross-section'),
aspect_from_label('count-fiber-a-gamma'),
null,
'summary'),
('delta a fiber count in fascicle cross section', -- address: n_a_delta
desc_inst_from_label('fascicle-cross-section'),
aspect_from_label('count-fiber-a-delta'),
null,
'summary'),
('b fiber count in fascicle cross section', -- address: n_b
desc_inst_from_label('fascicle-cross-section'),
aspect_from_label('count-fiber-b'),
null,
'summary'),
('unmyelinated fiber count in fascicle cross section', -- address: n_unmyel_nf
desc_inst_from_label('fascicle-cross-section'),
aspect_from_label('count-fiber-unmyelinated'),
null,
'summary'),
('nav fiber count in fascicle cross section', -- address: n_nav
desc_inst_from_label('fascicle-cross-section'),
aspect_from_label('count-fiber-nav'),
null,
'summary'),
('chat fiber count in fascicle cross section', -- address: n_chat
desc_inst_from_label('fascicle-cross-section'),
aspect_from_label('count-fiber-chat'),
null,
'summary'),
('myelinated fiber count in fascicle cross section', -- address: n_myelinated
desc_inst_from_label('fascicle-cross-section'),
aspect_from_label('count-fiber-myelinated'),
null,
'summary'),

-- fiber areas

('a fiber area in fascicle cross section um2',
desc_inst_from_label('fascicle-cross-section'),
aspect_from_label('area-fiber-a'),
unit_from_label('um2'),
'summary'),
('alpha a fiber area in fascicle cross section um2', -- address: area_a_alpha
desc_inst_from_label('fascicle-cross-section'),
aspect_from_label('area-fiber-a-alpha'),
unit_from_label('um2'),
'summary'),
('beta a fiber area in fascicle cross section um2', -- address: area_a_beta
desc_inst_from_label('fascicle-cross-section'),
aspect_from_label('area-fiber-a-beta'),
unit_from_label('um2'),
'summary'),
('gamma a fiber area in fascicle cross section um2', -- address: area_a_gamma
desc_inst_from_label('fascicle-cross-section'),
aspect_from_label('area-fiber-a-gamma'),
unit_from_label('um2'),
'summary'),
('delta a fiber area in fascicle cross section um2', -- address: area_a_delta
desc_inst_from_label('fascicle-cross-section'),
aspect_from_label('area-fiber-a-delta'),
unit_from_label('um2'),
'summary'),
('b fiber area in fascicle cross section um2', -- address: area_b
desc_inst_from_label('fascicle-cross-section'),
aspect_from_label('area-fiber-b'),
unit_from_label('um2'),
'summary'),
('unmyelinated fiber area in fascicle cross section um2', -- address: area_unmyel_nf
desc_inst_from_label('fascicle-cross-section'),
aspect_from_label('area-fiber-unmyelinated'),
unit_from_label('um2'),
'summary'),
('nav fiber area in fascicle cross section um2', -- address: area_nav
desc_inst_from_label('fascicle-cross-section'),
aspect_from_label('area-fiber-nav'),
unit_from_label('um2'),
'summary'),
('chat fiber area in fascicle cross section um2', -- address: area_chat
desc_inst_from_label('fascicle-cross-section'),
aspect_from_label('area-fiber-chat'),
unit_from_label('um2'),
'summary'),
('myelinated fiber area in fascicle cross section um2', -- address: area_myelinated
desc_inst_from_label('fascicle-cross-section'),
aspect_from_label('area-fiber-myelinated'),
unit_from_label('um2'),
'summary'),

-- address: crop_x_start
-- address: crop_x_stop
-- address: crop_y_start
-- address: crop_y_stop
-- address: chat_available
-- address: nav_available
-- address: th_available
-- address: x_pix
-- address: y_pix
-- address: x_um
-- address: y_um
-- address: x_cent
-- address: y_cent
-- address: rho
-- address: rho_pix
-- address: phi
-- address: epi_dist
-- address: epi_dist_inv
-- address: nerve_based_area
-- address: nerve_based_perimeter
-- address: nerve_based_eff_diam
-- address: perinerium_vertices
-- address: perinerium_vertices_px
-- address: nerve_based_shortest_diameter
-- address: hull_contrs
-- address: hull_contr_areas

('instance identifier', -- yes it sort of works but is it really a quantitative value about the thing? no it is just a pointer to the thing in some system
desc_inst_from_label('class thing'),
aspect_from_label('identifier-instance'),
null,
'instance')

;

INSERT INTO descriptors_cat (label, domain, range) VALUES
('hasAxonFiberType', NULL, 'controlled')

;

INSERT INTO descriptors_inst (iri, label) VALUES
('https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/simulation', 'simulation'), -- FIXME HACK placeholder to deal with virtual entities which is really an orthogonal axis here :/ because right now this causes all sorts of domain violations

('https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/myelin', 'myelin'),
('https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/myelin/cross-section', 'myelin-cross-section'),
('https://uri.interlex.org/tgbugs/uris/readable/quantdb/classes/extruded-plane', 'extruded-plane') -- for sites, no extra hierarchy yet
;

INSERT INTO controlled_terms (iri, label) VALUES
('https://uri.interlex.org/tgbugs/uris/readable/quantdb/controlled/axonFiberType/myelinated', 'myelinated'),
('https://uri.interlex.org/tgbugs/uris/readable/quantdb/controlled/axonFiberType/unmyelinated', 'unmyelinated')
;
