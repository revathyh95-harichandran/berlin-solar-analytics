{{
    config(
        materialized='table'
    )
}}

-- Installation fact: one row per solar unit (grain = installation_id).
-- Carries foreign keys out to the geography and date dimensions plus the
-- additive capacity measure.
--
-- Both dimension joins are inner joins by construction: the dimensions are
-- built from this same staging model, so every fact row is guaranteed a
-- match. The staging layer already coalesced missing geography to 'Unknown'.

with installations as (

    select * from {{ ref('stg_solar_installations') }}

),

geography as (

    select * from {{ ref('dim_geography') }}

),

dates as (

    select * from {{ ref('dim_date') }}

),

final as (

    select
        installations.installation_id,
        geography.geo_id,
        dates.install_date,
        installations.capacity_kw

    from installations

    inner join geography
        on  installations.city        = geography.city
        and installations.state       = geography.state
        and installations.postal_code = geography.postal_code

    inner join dates
        on installations.install_date = dates.install_date

)

select * from final
