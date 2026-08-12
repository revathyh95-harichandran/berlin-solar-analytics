{{
    config(
        materialized='table'
    )
}}

-- Geography dimension: one row per distinct city / state / postal_code.
-- The surrogate key is a hash of the natural key so it stays stable across
-- full refreshes (a row_number() would reshuffle on every run).

with locations as (

    select distinct
        city,
        state,
        postal_code

    from {{ ref('stg_solar_installations') }}

),

final as (

    select
        md5(
            coalesce(city, '') || '|' ||
            coalesce(state, '') || '|' ||
            coalesce(postal_code, '')
        )                as geo_id,
        city,
        state,
        postal_code

    from locations

)

select * from final
