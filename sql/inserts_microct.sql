/*
MicroCT dataset lookup data inserts.
Dataset: REVA CD MicroCT (fb1cbd05-4320-4d8b-ac3a-44f1fe810718)

All inserts use ON CONFLICT DO NOTHING for idempotency.
ALTER TYPE uses DO $$ ... END $$ block with IF NOT EXISTS guard.
*/

-- =========================================================================
-- 1. New units: mm, mm2
-- =========================================================================

INSERT INTO units (iri, label) VALUES
('http://uri.interlex.org/tgbugs/uris/readable/aspect/unit/millimeter', 'mm'),
('http://uri.interlex.org/tgbugs/uris/readable/aspect/unit/mm2', 'mm2')
ON CONFLICT (label) DO NOTHING;

-- =========================================================================
-- 2. ALTER TYPE quant_agg_type ADD VALUE 'sd' (with IF NOT EXISTS guard)
-- =========================================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_enum
        WHERE enumtypid = 'quantdb.quant_agg_type'::regtype
        AND enumlabel = 'sd'
    ) THEN
        ALTER TYPE quantdb.quant_agg_type ADD VALUE 'sd';
    END IF;
END
$$;

-- =========================================================================
-- 3. New aspects for MicroCT measurements
-- =========================================================================

INSERT INTO aspects (iri, label) VALUES
('http://uri.interlex.org/tgbugs/uris/readable/aspect/major-axis', 'major-axis'),
('http://uri.interlex.org/tgbugs/uris/readable/aspect/minor-axis', 'minor-axis'),
('http://uri.interlex.org/tgbugs/uris/readable/aspect/count/fascicle', 'count-fascicle'),
('http://uri.interlex.org/tgbugs/uris/readable/aspect/area/endoneurial', 'area-endoneurial'),
('http://uri.interlex.org/tgbugs/uris/readable/aspect/frame-index', 'frame-index')
ON CONFLICT (label) DO NOTHING;

-- =========================================================================
-- 4. Aspect parent entries for new aspects
-- =========================================================================

INSERT INTO aspect_parent (parent, id) VALUES
(aspect_from_label('length'), aspect_from_label('major-axis')),
(aspect_from_label('length'), aspect_from_label('minor-axis')),
(aspect_from_label('count'), aspect_from_label('count-fascicle')),
(aspect_from_label('area'), aspect_from_label('area-endoneurial'))
ON CONFLICT DO NOTHING;

-- =========================================================================
-- 5. Boolean controlled_terms for GraphML edge properties
-- =========================================================================

INSERT INTO controlled_terms (iri, label) VALUES
('https://uri.interlex.org/tgbugs/uris/readable/quantdb/controlled/boolean/true', 'true'),
('https://uri.interlex.org/tgbugs/uris/readable/quantdb/controlled/boolean/false', 'false')
ON CONFLICT (label) DO NOTHING;

-- =========================================================================
-- 6. NerveMorphology.csv per-slice descriptors_quant (um/um2 units)
--    Columns: area, perimeter, eq_diameter, center_x, center_y,
--             major_axis, minor_axis, angle
--    NOTE: 'nerve cross section diameter um' (id=13) already exists in
--    f006 — ON CONFLICT DO NOTHING will skip it. Same for angle degree.
-- =========================================================================

INSERT INTO descriptors_quant (label, domain, aspect, unit, aggregation_type) VALUES
('nerve cross section area um2',
 desc_inst_from_label('nerve-cross-section'),
 aspect_from_label('area'),
 unit_from_label('um2'),
 'instance'),

('nerve cross section perimeter um',
 desc_inst_from_label('nerve-cross-section'),
 aspect_from_label('perimeter'),
 unit_from_label('um'),
 'instance'),

('nerve cross section diameter um',
 desc_inst_from_label('nerve-cross-section'),
 aspect_from_label('diameter'),
 unit_from_label('um'),
 'instance'),

('nerve cross section centroid-x um',
 desc_inst_from_label('nerve-cross-section'),
 aspect_from_label('centroid-x'),
 unit_from_label('um'),
 'instance'),

('nerve cross section centroid-y um',
 desc_inst_from_label('nerve-cross-section'),
 aspect_from_label('centroid-y'),
 unit_from_label('um'),
 'instance'),

('nerve cross section major axis um',
 desc_inst_from_label('nerve-cross-section'),
 aspect_from_label('major-axis'),
 unit_from_label('um'),
 'instance'),

('nerve cross section minor axis um',
 desc_inst_from_label('nerve-cross-section'),
 aspect_from_label('minor-axis'),
 unit_from_label('um'),
 'instance'),

('nerve cross section angle degree',
 desc_inst_from_label('nerve-cross-section'),
 aspect_from_label('angle'),
 unit_from_label('degree'),
 'instance')

ON CONFLICT (label) DO NOTHING;

-- =========================================================================
-- 7. GraphML fascicle node descriptors_quant (um/um2 units)
--    Columns: area, equivalent_diameter, centroid-0, centroid-1,
--             ellipse_major_axis, ellipse_minor_axis, ellipse_angle
--    NOTE: 'fascicle cross section area um2' (id=32) and
--    'fascicle cross section diameter um' (id=14) already exist in f006 —
--    ON CONFLICT DO NOTHING will skip them.
-- =========================================================================

INSERT INTO descriptors_quant (label, domain, aspect, unit, aggregation_type) VALUES
('fascicle cross section area um2',
 desc_inst_from_label('fascicle-cross-section'),
 aspect_from_label('area'),
 unit_from_label('um2'),
 'instance'),

('fascicle cross section diameter um',
 desc_inst_from_label('fascicle-cross-section'),
 aspect_from_label('diameter'),
 unit_from_label('um'),
 'instance'),

('fascicle cross section centroid-0 um',
 desc_inst_from_label('fascicle-cross-section'),
 aspect_from_label('centroid-x'),
 unit_from_label('um'),
 'instance'),

('fascicle cross section centroid-1 um',
 desc_inst_from_label('fascicle-cross-section'),
 aspect_from_label('centroid-y'),
 unit_from_label('um'),
 'instance'),

('fascicle cross section ellipse major axis um',
 desc_inst_from_label('fascicle-cross-section'),
 aspect_from_label('major-axis'),
 unit_from_label('um'),
 'instance'),

('fascicle cross section ellipse minor axis um',
 desc_inst_from_label('fascicle-cross-section'),
 aspect_from_label('minor-axis'),
 unit_from_label('um'),
 'instance'),

('fascicle cross section ellipse angle degree',
 desc_inst_from_label('fascicle-cross-section'),
 aspect_from_label('angle'),
 unit_from_label('degree'),
 'instance')

ON CONFLICT (label) DO NOTHING;

-- =========================================================================
-- 8. SummaryMorphology descriptors_quant (mm/mm2 units)
--    BranchMorphology.csv and CranialNervesMorphology.csv columns
-- =========================================================================

INSERT INTO descriptors_quant (label, domain, aspect, unit, aggregation_type) VALUES
('median nerve diameter mm',
 desc_inst_from_label('nerve'),
 aspect_from_label('diameter'),
 unit_from_label('mm'),
 'media'),

('sd nerve diameter mm',
 desc_inst_from_label('nerve'),
 aspect_from_label('diameter'),
 unit_from_label('mm'),
 'sd'),

('median nerve area mm2',
 desc_inst_from_label('nerve'),
 aspect_from_label('area'),
 unit_from_label('mm2'),
 'media'),

('sd nerve area mm2',
 desc_inst_from_label('nerve'),
 aspect_from_label('area'),
 unit_from_label('mm2'),
 'sd'),

('endoneurial area mm2',
 desc_inst_from_label('nerve'),
 aspect_from_label('area-endoneurial'),
 unit_from_label('mm2'),
 'instance'),

('fascicle count',
 desc_inst_from_label('nerve'),
 aspect_from_label('count-fascicle'),
 unit_from_label('unitless'),
 'instance'),

('avg fascicle diameter mm',
 desc_inst_from_label('fascicle-cross-section'),
 aspect_from_label('diameter'),
 unit_from_label('mm'),
 'mean'),

('sd fascicle diameter mm',
 desc_inst_from_label('fascicle-cross-section'),
 aspect_from_label('diameter'),
 unit_from_label('mm'),
 'sd'),

('min fascicle diameter mm',
 desc_inst_from_label('fascicle-cross-section'),
 aspect_from_label('diameter'),
 unit_from_label('mm'),
 'min'),

('max fascicle diameter mm',
 desc_inst_from_label('fascicle-cross-section'),
 aspect_from_label('diameter'),
 unit_from_label('mm'),
 'max'),

('measurement distance mm',
 desc_inst_from_label('nerve'),
 aspect_from_label('distance'),
 unit_from_label('mm'),
 'instance'),

('measurement frame',
 desc_inst_from_label('nerve'),
 aspect_from_label('frame-index'),
 unit_from_label('unitless'),
 'instance'),

('global distance mm',
 desc_inst_from_label('nerve'),
 aspect_from_label('distance-along-axis'),
 unit_from_label('mm'),
 'instance')

ON CONFLICT (label) DO NOTHING;

-- =========================================================================
-- 9. GraphML edge descriptors_cat
--    NOTE: domain is NULL so ON CONFLICT (domain, range, label) cannot
--    catch duplicates (NULL != NULL in SQL). Use WHERE NOT EXISTS guard.
--    First, clean up any duplicate rows from prior non-idempotent runs.
-- =========================================================================

DELETE FROM descriptors_cat
WHERE label IN ('fascicleEdgeIdentity', 'fascicleEdgeSplit', 'fascicleEdgeMerge')
AND id NOT IN (
    SELECT MIN(id)
    FROM descriptors_cat
    WHERE label IN ('fascicleEdgeIdentity', 'fascicleEdgeSplit', 'fascicleEdgeMerge')
    GROUP BY label
);

INSERT INTO descriptors_cat (label, domain, range)
SELECT 'fascicleEdgeIdentity', NULL, 'controlled'
WHERE NOT EXISTS (
    SELECT 1 FROM descriptors_cat
    WHERE label = 'fascicleEdgeIdentity' AND domain IS NULL
);

INSERT INTO descriptors_cat (label, domain, range)
SELECT 'fascicleEdgeSplit', NULL, 'controlled'
WHERE NOT EXISTS (
    SELECT 1 FROM descriptors_cat
    WHERE label = 'fascicleEdgeSplit' AND domain IS NULL
);

INSERT INTO descriptors_cat (label, domain, range)
SELECT 'fascicleEdgeMerge', NULL, 'controlled'
WHERE NOT EXISTS (
    SELECT 1 FROM descriptors_cat
    WHERE label = 'fascicleEdgeMerge' AND domain IS NULL
);
