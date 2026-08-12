{{
    config(
        materialized='view'
    )
}}

-- Staging layer: one row per operating solar unit.
-- Trims and standardises the raw MaStR fields, replaces missing geography
-- with an explicit 'Unknown' member so dimension joins never drop facts,
-- and keeps only units that are actually in operation.

with source as (

    select * from {{ source('mastr', 'raw_solar_installations') }}

),

cleaned as (

    select
        nullif(trim(installation_id), '')          as installation_id,
        nullif(trim(state), '')                    as state,
        nullif(trim(city), '')                     as city,
        nullif(trim(postal_code), '')              as postal_code,
        cast(capacity_kw as double)                as capacity_kw,
        cast(install_date as date)                 as install_date,
        nullif(trim(status), '')                   as status

    from source

),

final as (

    select
        installation_id,
        coalesce(state, 'Unknown')       as state,
        coalesce(city, 'Unknown')        as city,
        coalesce(postal_code, 'Unknown') as postal_code,
        capacity_kw,
        install_date,
        status

    from cleaned

    where installation_id is not null
      and status = 'In Betrieb'
      and capacity_kw is not null
      and capacity_kw > 0
      and install_date is not null

)

select * from final
