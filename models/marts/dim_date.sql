{{
    config(
        materialized='table'
    )
}}

-- Date dimension: one row per distinct commissioning date present in the
-- facts. install_date is the primary key, so the fact table can carry the
-- date itself as its foreign key.

with dates as (

    select distinct
        install_date

    from {{ ref('stg_solar_installations') }}

    where install_date is not null

),

final as (

    select
        install_date,
        cast(extract(year    from install_date) as integer) as year,
        cast(extract(quarter from install_date) as integer) as quarter,
        cast(extract(month   from install_date) as integer) as month,
        strftime(install_date, '%B')                        as month_name,
        cast(extract(day     from install_date) as integer) as day_of_month,
        strftime(install_date, '%Y-Q') ||
            cast(extract(quarter from install_date) as varchar) as year_quarter,
        strftime(install_date, '%Y-%m')                     as year_month

    from dates

)

select * from final
