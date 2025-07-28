#!/usr/bin/env python3
"""
Static analysis test for f006_csv_with_export.py to verify it implements the table population guide.

This test analyzes the source code without importing it, avoiding Python 3.13/SQLAlchemy compatibility issues.
"""

import ast
import os
import re


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
    get_or_create_used = False

    # Extract imports
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == 'quantdb.models':
            for alias in node.names:
                imported_models.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module == 'quantdb.generic_ingest':
            for alias in node.names:
                if alias.name == 'back_populate_tables':
                    back_populate_used = True
                elif alias.name == 'get_or_create':
                    get_or_create_used = True
        elif isinstance(node, ast.FunctionDef):
            functions_defined.add(node.name)

    # Check for specific function calls in the code
    create_leaf_values_uses_back_populate = (
        'back_populate_tables(session, values_cat)' in content
        and 'back_populate_tables(session, values_quant)' in content
    )

    # Analyze table creation order by looking at function calls in run_f006_ingestion
    order_pattern = re.compile(
        r'create_basic_descriptors.*?'
        r'ingest_objects_table.*?'
        r'ingest_instances_table.*?'
        r'create_obj_desc_mappings.*?'
        r'create_leaf_values',
        re.DOTALL,
    )
    correct_order = bool(order_pattern.search(content))

    # Print analysis results
    print('=== F006 Implementation Analysis ===\n')

    # 1. Check root tables
    print('1. ROOT TABLES (should all be imported):')
    root_tables = ['Addresses', 'Aspects', 'Units', 'ControlledTerms', 'DescriptorsInst', 'Objects']
    for table in root_tables:
        status = '✓' if table in imported_models else '✗'
        print(f'   {status} {table}')

    # Check if Addresses are created in the code
    addresses_created = 'Addresses(' in content
    print(f"   {'✓' if addresses_created else '✗'} Addresses (created in code)")

    # 2. Check intermediate tables
    print('\n2. INTERMEDIATE TABLES (should all be imported):')
    intermediate_tables = [
        'DescriptorsCat',
        'DescriptorsQuant',
        'ValuesInst',
        'ObjDescInst',
        'ObjDescCat',
        'ObjDescQuant',
    ]
    for table in intermediate_tables:
        status = '✓' if table in imported_models else '✗'
        print(f'   {status} {table}')

    # 3. Check leaf tables
    print('\n3. LEAF TABLES (should use back_populate_tables):')
    leaf_tables = ['ValuesCat', 'ValuesQuant']
    for table in leaf_tables:
        status = '✓' if table in imported_models else '✗'
        print(f'   {status} {table}')
    print(f"   {'✓' if create_leaf_values_uses_back_populate else '✗'} Uses back_populate_tables for leaf tables")

    # 4. Check helper functions
    print('\n4. HELPER FUNCTIONS:')
    print(f"   {'✓' if get_or_create_used else '✗'} Imports get_or_create")
    print(f"   {'✓' if back_populate_used else '✗'} Imports back_populate_tables")

    # 5. Check required functions
    print('\n5. REQUIRED FUNCTIONS:')
    required_functions = [
        'create_basic_descriptors',
        'ingest_objects_table',
        'ingest_instances_table',
        'create_obj_desc_mappings',
        'create_leaf_values',
        'run_f006_ingestion',
    ]
    for func in required_functions:
        status = '✓' if func in functions_defined else '✗'
        print(f'   {status} {func}')

    # 6. Check population order
    print('\n6. POPULATION ORDER:')
    print(f"   {'✓' if correct_order else '✗'} Functions called in correct order")

    # 7. Specific checks
    print('\n7. SPECIFIC IMPLEMENTATIONS:')

    # Check if Aspects and Units are created
    aspects_created = '"volume"' in content and '"diameter"' in content and '"length"' in content
    units_created = '"mm3"' in content and '"um"' in content and '"mm"' in content
    print(f"   {'✓' if aspects_created else '✗'} Creates Aspects (volume, length, diameter)")
    print(f"   {'✓' if units_created else '✗'} Creates Units (mm3, mm, um)")

    # Check if DescriptorsQuant are created with dependencies
    desc_quant_created = 'DescriptorsQuant(' in content and 'unit=' in content and 'aspect=' in content
    print(f"   {'✓' if desc_quant_created else '✗'} Creates DescriptorsQuant with unit and aspect dependencies")

    # Summary
    all_root_imported = all(table in imported_models for table in root_tables[1:])  # Excluding Addresses
    all_intermediate_imported = all(table in imported_models for table in intermediate_tables)
    all_leaf_imported = all(table in imported_models for table in leaf_tables)
    all_functions_defined = all(func in functions_defined for func in required_functions)

    print('\n=== SUMMARY ===')
    if (
        all_root_imported
        and addresses_created
        and all_intermediate_imported
        and all_leaf_imported
        and all_functions_defined
        and correct_order
        and create_leaf_values_uses_back_populate
        and aspects_created
        and units_created
    ):
        print('✅ F006 properly implements the table population guide!')
        return True
    else:
        print('❌ F006 has some issues with the implementation')
        return False


if __name__ == '__main__':
    success = analyze_f006_implementation()
    exit(0 if success else 1)
