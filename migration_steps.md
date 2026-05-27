1. Import database from prod
2. python manage.py dbshell < sqlscripts/bfrs_bushfire_v_view.sql
3. python manage.py dbshell < sqlscripts/bushfire_final_fireboundary_latest_view.sql
4. python manage.py dbshell < sqlscripts/bushfire_fireboundary_latest_view.sql
5. python manage.py dbshell < sqlscripts/bushfire_latest_view.sql
6. python manage.py dbshell < sqlscripts/bushfirelist_latest_view.sql
7. python manage.py migrate
8. python manage.py complete_reporting_cadastre_update
9. python manage.py complete_bfrs_region_update
10. python manage.py  complete_reporting_dept_interest
11. python manage.py complete_reporting_legislated_tenure
12. python manage.py complete_reporting_state_forest
    

