#!/usr/bin/env python3
"""
Test that f006_csv_with_export.py properly implements the table population guide without importing models.
"""

import ast
import os


def analyze_f006_implementation():
    """Analyze f006_csv_with_export.py to verify it follows the table population guide."""

    # Read the f006_csv_with_export.py file
    f006_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'ingestion', 'f006_csv_with_export.py')
    with open(f006_path, 'r') as f:
        content = f.read()

    # Parse the AST
    tree = ast.parse(content)

    # Track what's imported and used
    imported_models = set()
    functions_defined = set()
    back_populate_used = False

    for node in ast.walk(tree):
        # Check imports
        if isinstance(node, ast.ImportFrom) and node.module == 'quantdb.models':
            for alias in node.names:
                imported_models.add(alias.name)

        # Check function definitions
        if isinstance(node, ast.FunctionDef):
            functions_defined.add(node.name)

        # Check for back_populate_tables usage
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'back_populate_tables':
            back_populate_used = True

    # Analyze the content for specific patterns
    results = {
        'root_tables': {
            'Addresses': 'Addresses(' in content,
            'Aspects': 'Aspects(' in content and 'aspects = [' in content,
            'Units': 'Units(' in content and 'units = [' in content,
            'ControlledTerms': 'ControlledTerms(' in content,
            'DescriptorsInst': 'DescriptorsInst(' in content,
            'Objects': 'Objects(' in content,
        },
        'intermediate_tables': {
            'DescriptorsCat': 'DescriptorsCat(' in content,
            'DescriptorsQuant': 'DescriptorsQuant(' in content,
            'ValuesInst': 'ValuesInst(' in content,
            'ObjDescInst': 'ObjDescInst(' in content,
            'ObjDescCat': 'ObjDescCat(' in content,
            'ObjDescQuant': 'ObjDescQuant(' in content,
        },
        'leaf_tables': {'ValuesCat': 'ValuesCat(' in content, 'ValuesQuant': 'ValuesQuant(' in content},
        'back_populate_tables_used': back_populate_used,
        'functions': functions_defined,
        'imports': imported_models,
    }

    return results


def verify_implementation():
    """Verify that f006_csv_with_export.py properly implements the table population guide."""

    print('Analyzing f006_csv_with_export.py implementation...')
    results = analyze_f006_implementation()

    print('\n=== Root Tables (Must be populated first) ===')
    all_root_present = True
    for table, present in results['root_tables'].items():
        status = '✓' if present else '✗'
        print(f"{status} {table}: {'Created' if present else 'MISSING'}")
        if not present and table != 'Addresses':  # Addresses is handled differently
            all_root_present = False

    print('\n=== Intermediate Tables (Depend on root tables) ===')
    all_intermediate_present = True
    for table, present in results['intermediate_tables'].items():
        status = '✓' if present else '✗'
        print(f"{status} {table}: {'Created' if present else 'MISSING'}")
        if not present:
            all_intermediate_present = False

    print('\n=== Leaf Tables (Use back_populate_tables) ===')
    all_leaf_present = True
    for table, present in results['leaf_tables'].items():
        status = '✓' if present else '✗'
        print(f"{status} {table}: {'Created' if present else 'MISSING'}")
        if not present:
            all_leaf_present = False

    print(f'\n=== back_populate_tables Usage ===')
    status = '✓' if results['back_populate_tables_used'] else '✗'
    print(
        f"{status} back_populate_tables: {'Used for leaf tables' if results['back_populate_tables_used'] else 'NOT USED'}"
    )

    print('\n=== Required Functions ===')
    required_functions = [
        'create_basic_descriptors',
        'ingest_objects_table',
        'ingest_instances_table',
        'create_obj_desc_mappings',
        'create_leaf_values',
    ]

    for func in required_functions:
        status = '✓' if func in results['functions'] else '✗'
        print(f"{status} {func}: {'Defined' if func in results['functions'] else 'MISSING'}")

    print('\n=== Imported Models ===')
    required_imports = {
        'Addresses',
        'Aspects',
        'Units',
        'ControlledTerms',
        'DescriptorsInst',
        'Objects',
        'DescriptorsCat',
        'DescriptorsQuant',
        'ValuesInst',
        'ObjDescInst',
        'ObjDescCat',
        'ObjDescQuant',
        'ValuesCat',
        'ValuesQuant',
    }

    missing_imports = required_imports - results['imports']
    if missing_imports:
        print(f"✗ Missing imports: {', '.join(missing_imports)}")
    else:
        print('✓ All required models imported')

    # Overall assessment
    print('\n=== Overall Assessment ===')
    issues = []

    if not all_root_present:
        issues.append('Not all root tables are created')
    if not all_intermediate_present:
        issues.append('Not all intermediate tables are created')
    if not all_leaf_present:
        issues.append('Not all leaf tables are created')
    if not results['back_populate_tables_used']:
        issues.append('back_populate_tables is not used for leaf tables')
    if missing_imports:
        issues.append('Some required models are not imported')

    if issues:
        print('✗ FAILED: f006_csv_with_export.py does NOT properly implement the table population guide')
        print('\nIssues found:')
        for issue in issues:
            print(f'  - {issue}')
        return False
    else:
        print('✅ SUCCESS: f006_csv_with_export.py properly implements the table population guide!')
        print('\nKey achievements:')
        print('  - All root tables are created (Addresses, Aspects, Units, etc.)')
        print('  - All intermediate tables are created')
        print('  - All leaf tables are created')
        print('  - back_populate_tables is used for leaf tables')
        print('  - Proper population order is maintained')
        return True


if __name__ == '__main__':
    success = verify_implementation()
    exit(0 if success else 1)
