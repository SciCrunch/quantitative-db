-- CONNECT TO quantdb_test USER "quantdb-user";

\set dataset_uuid_1 {8b9e0f61-401f-4b9a-a26c-5d8a1481976f}
\set dataset_uuid_2 {77758d88-b525-4d51-be1c-05428ecb2f62}
\set dataset_uuid_3 {18a29eff-ff2e-446f-892c-393f9055457e}
\set dataset_uuid_4 {c88750d4-ce18-4a96-b00b-6b23ee6717a4}

\set package_uuid_1 {1ff97dbc-05e0-4c53-8c92-31a7b9bf75ab}
\set package_uuid_2 {6b823093-a26a-4930-95c5-3f2bc3cfe516}
\set package_uuid_3 {527e9cfe-7925-414c-bcab-72c96813293c}

\set internal_uuid_1 {2d0267ee-6fb9-449a-b0c3-3a46d1fc5783}
\set max_uuid        {ffffffff-ffff-ffff-ffff-ffffffffffff} -- ignore the limits of 4 and b for now

SELECT ensure_test_user();

INSERT INTO objects (id_type, id) VALUES
('dataset', :'dataset_uuid_1'),
('dataset', :'dataset_uuid_2'),
('dataset', :'dataset_uuid_3'),
('dataset', :'dataset_uuid_4')
;

/* -- TODO test-negative
INSERT INTO objects (id_type, id) VALUES
('package', :'package_uuid_1')
;
*/

INSERT INTO objects (id_type, id, id_file) VALUES
('package', :'package_uuid_1', 0),
('package', :'package_uuid_2', 0),
('package', :'package_uuid_3', 0)
;

INSERT INTO objects_internal (id, label) VALUES
(:'internal_uuid_1', 'trigger_objects_uuid_zero_to_one')
;

INSERT INTO objects (id_type, id, id_internal) VALUES
('quantdb', :'internal_uuid_1', :'internal_uuid_1')
;

INSERT INTO obj_desc_inst (object, desc_inst, addr_field) VALUES
(:'package_uuid_1',
desc_inst_from_label('fascicle-cross-section'),
address_from_fadd_type_fadd('tabular-header', 'id'))
;

INSERT INTO obj_desc_cat (object, desc_cat, addr_field) VALUES
(:'package_uuid_1', -- FIXME obviously a bad example because there could be multiple positive strains
desc_cat_from_label_domain_label('fasciclePositiveStainType', 'fascicle-cross-section'),
address_from_fadd_type_fadd_vtype('tabular-header', 'stain', 'multi')),

(:'package_uuid_1',
desc_cat_from_label_domain_label('fascicleNegativeStainType', 'fascicle-cross-section'),
address_from_fadd_type_fadd_vtype('tabular-header', 'stain-negative', 'multi'))

;

INSERT INTO obj_desc_quant (object, desc_quant, addr_field) VALUES
(:'package_uuid_1',
desc_quant_from_label('fascicle cross section diameter um'),
address_from_fadd_type_fadd('tabular-header', 'diameter')),

(:'package_uuid_1',
desc_quant_from_label('fascicle cross section diameter um min'),
address_from_fadd_type_fadd('tabular-header', 'diameter-min')),

(:'package_uuid_1',
desc_quant_from_label('fascicle cross section diameter um max'),
address_from_fadd_type_fadd('tabular-header', 'diameter-max'))

;

-- query to get object ids that have not been extracted at all
SELECT objects.id_type, oid.object FROM obj_desc_inst AS oid
LEFT JOIN values_quant as qv
ON oid.object = qv.object
LEFT JOIN values_cat as cv
ON oid.object = cv.object
JOIN objects ON oid.object = objects.id
WHERE qv.object is NULL AND cv.object is NULL;

SELECT * FROM get_all_values_example();
SELECT 'guo-1';
SELECT * FROM get_unextracte_objects();

/*
-- more granular query to get object ids where cat or quant data have not
-- been extracted for the specific descriptors that have been specified
-- this makes it possible to do incremental extraction
SELECT objects.id_type, oqd.object FROM obj_desc_quant AS oqd
LEFT JOIN values_quant as qv
ON oqd.object = qv.object
JOIN objects ON oqd.object = objects.id AND oqd.desc_quant = qv.desc_quant
WHERE qv.object is NULL

UNION

SELECT objects.id_type, ocd.object FROM obj_desc_cat AS ocd
-- FIXME this can't detect cases where an UPDATE modified a desc_cat address value type or changed an address
-- e.g. if a curator makes a mistake, I guess we can have a force rerun option or add an AFTER UPDATE trigger
-- the obj_x_descriptor tables ??
LEFT JOIN values_cat as cv
ON ocd.object = cv.object
JOIN objects ON ocd.object = objects.id AND ocd.desc_cat = cv.desc_cat
WHERE cv.object is NULL;
*/

-- the order of inserts here more or less corresponds to the order needed for the workflow

INSERT INTO values_inst (type, desc_inst, dataset, id_formal, id_sub, id_sam) VALUES
('subject', desc_inst_from_label('human'), :'dataset_uuid_1', 'sub-1', 'sub-1', NULL),
('sample', desc_inst_from_label('nerve-volume'), :'dataset_uuid_1', 'sam-l', 'sub-1', 'sam-l'), -- FIXME and here we see the issue with nerve vs nerve-thing
('sample', desc_inst_from_label('nerve-cross-section'), :'dataset_uuid_1', 'sam-l-seg-c7-A-level-1', 'sub-1', 'sam-l-seg-c7-A-level-1'),

('subject', desc_inst_from_label('human'), :'dataset_uuid_2', 'sub-1', 'sub-1', NULL),
('subject', desc_inst_from_label('human'), :'dataset_uuid_3', 'sub-1', 'sub-1', NULL),
('subject', desc_inst_from_label('human'), :'dataset_uuid_4', 'sub-1', 'sub-1', NULL)
;

SELECT * FROM  values_inst;

INSERT INTO equiv_inst (left_thing, right_thing) VALUES (1, 2);
SELECT * FROM  equiv_inst ORDER BY left_thing;

INSERT INTO equiv_inst (left_thing, right_thing) VALUES (3, 4);
SELECT * FROM  equiv_inst ORDER BY left_thing;

SELECT * FROM get_all_equivs(2, 3);
INSERT INTO equiv_inst (left_thing, right_thing) VALUES (2, 3);
SELECT * FROM  equiv_inst ORDER BY left_thing;

/*
INSERT INTO instance_subject (id, subject) VALUES
(inst_from_dataset_id(:'dataset_uuid_1', 'sam-l'), inst_from_dataset_id(:'dataset_uuid_1', 'sub-1')),
(inst_from_dataset_id(:'dataset_uuid_1', 'sam-l-seg-c7-A-level-1'), inst_from_dataset_id(:'dataset_uuid_1', 'sub-1'))
;
*/

INSERT INTO values_inst (type, desc_inst, dataset, id_formal, id_sub, id_sam) VALUES
(
'below',
desc_inst_from_label('fascicle-cross-section'),
:'dataset_uuid_1',
'fsccs-1',
'sub-1',
'sam-l-seg-c7-A-level-1'
)
;

INSERT INTO instance_parent (id, parent) VALUES
(inst_from_dataset_id(:'dataset_uuid_1', 'sam-l'), inst_from_dataset_id(:'dataset_uuid_1', 'sub-1')),
(inst_from_dataset_id(:'dataset_uuid_1', 'sam-l-seg-c7-A-level-1'), inst_from_dataset_id(:'dataset_uuid_1', 'sam-l')),
(inst_from_dataset_id(:'dataset_uuid_1', 'fsccs-1'), inst_from_dataset_id(:'dataset_uuid_1', 'sam-l-seg-c7-A-level-1'))
;

/*
INSERT INTO instance_subject (id, subject) VALUES
(inst_from_dataset_id(:'dataset_uuid_1', 'fsccs-1'), inst_from_dataset_id(:'dataset_uuid_1', 'sub-1'))
;

INSERT INTO instance_sample (id, sample) VALUES
(inst_from_dataset_id(:'dataset_uuid_1', 'fsccs-1'), inst_from_dataset_id(:'dataset_uuid_1', 'sam-l-seg-c7-A-level-1'))
;
*/

INSERT INTO values_cat (object, desc_inst, desc_cat, instance, value_open, value_controlled) VALUES
(
:'package_uuid_1',
desc_inst_from_label('fascicle-cross-section'),
desc_cat_from_label_domain_label('fasciclePositiveStainType', 'fascicle-cross-section'),
inst_from_dataset_id(:'dataset_uuid_1', 'fsccs-1'),
'chat',
cterm_from_label('chat')
)
;

INSERT INTO values_quant (object, desc_inst, desc_quant, instance, value_blob, value) VALUES
 -- FIXME TODO ensure that dataset/package combo matches and is present
(
:'package_uuid_1',
desc_inst_from_label('fascicle-cross-section'), -- TODO automate filling from inst itself probably since it is more for convenience here
desc_quant_from_label('fascicle cross section diameter um'),
inst_from_dataset_id(:'dataset_uuid_1', 'fsccs-1'),
to_jsonb(342),
342
)
;

SELECT * FROM get_all_values_example();
SELECT 'guo-2';
SELECT * FROM get_unextracte_objects();

-- hierachy testing
SELECT * FROM get_parent_aspect(aspect_from_label('diameter-orthogonal-to-anterior-posterior-axis'));
SELECT * FROM get_aspect_parent_edges(aspect_from_label('diameter-orthogonal-to-anterior-posterior-axis'));
SELECT * FROM get_all_parents_aspect();

SELECT * FROM get_parent_desc_inst(desc_inst_from_label('fascicle-cross-section'));
SELECT * FROM get_class_parent_edges(desc_inst_from_label('fascicle-cross-section'));
SELECT * FROM get_all_parents_desc_inst();

SELECT * FROM get_parent_inst(inst_from_dataset_id(:'dataset_uuid_1', 'fsccs-1'));
SELECT * FROM get_instance_parent_edges(inst_from_dataset_id(:'dataset_uuid_1', 'fsccs-1'));
SELECT * FROM get_all_parents_inst();

-- hrm do we need get_x_children? answer seems to be yes?

-- top down hierarchical query
-- FIXME almost certainly faster to call get_child_aspect once and then do where a0.id in aspect_children ...
-- using explain we can see that this version get_parent_aspect in a loop for all aspects (I think) which is dumb
-- but the query planner may be able to figure it out diesn't actually need to do that for the entire sub select
-- but only for a0.id ??? yeah, seems so
/*
select * from values_quant as qv
join descriptors_quant as qd on qv.desc_quant = qd.id
join aspects as a0 on qd.aspect = a0.id
join (select a.id, p.parent from aspects as a cross join get_parent_aspect(a.id) as p) as ap on ap.id = a0.id
where ap.parent = aspect_from_label('distance');
*/

-- FIXME for our join use case we likely want this to include the starting class itself
SELECT * FROM get_child_aspect(aspect_from_label('distance'));
SELECT * FROM get_aspect_child_edges(aspect_from_label('distance'));

SELECT * FROM get_child_aspect(aspect_from_label('diameter'));
SELECT * FROM get_aspect_child_edges(aspect_from_label('diameter'));

select qv from get_child_aspect(aspect_from_label('distance')) as ap
join descriptors_quant as qd on qd.aspect = ap.child
join values_quant as qv on qv.desc_quant = qd.id;

--SELECT * FROM get_child_desc_inst(desc_inst_from_label('participant'));

SELECT cm.label FROM get_child_desc_inst(desc_inst_from_label('participant')) as c join descriptors_inst as cm on c.child = cm.id ;
SELECT cm.label FROM get_child_desc_inst(desc_inst_from_label('nerve')) as c join descriptors_inst as cm on c.child = cm.id ;
