# Extraction-layer validation notes

- The extraction-layer contract expects entity extraction to translate both `NCBITaxon_9606` and `ncbitaxon:9606` to the `human` descriptor. The cached f006 payload exercises the OntTerm/URL form, so alias-specific tests are still needed to cover the uppercase compact identifier.
- The cached f006 Cassava `path-metadata.json` contains zero CSV entries. Any real-data fascicle/fiber extraction path therefore needs a discovery or fetch strategy beyond scanning cached `path_metadata` blobs for `fascicles.csv` and `fibers.csv`.
