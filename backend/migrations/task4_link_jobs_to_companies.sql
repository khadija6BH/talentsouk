-- Idempotent Task 4 migration. Run with database-owner privileges.
-- Keeps company_name and existing data unchanged.

create extension if not exists unaccent;

alter table public.jobs
    add column if not exists company_id bigint;

do $$
begin
    if not exists (
        select 1
        from pg_constraint
        where conname = 'jobs_company_id_fkey'
          and conrelid = 'public.jobs'::regclass
    ) then
        alter table public.jobs
            add constraint jobs_company_id_fkey
            foreign key (company_id)
            references public.companies(id)
            on update cascade
            on delete set null;
    end if;
end $$;

create index if not exists jobs_company_id_idx
    on public.jobs(company_id);

with normalized_companies as (
    select
        min(id) as id,
        trim(regexp_replace(lower(unaccent(name)), '[^a-z0-9]+', ' ', 'g')) as normalized_name
    from public.companies
    where nullif(trim(name), '') is not null
    group by trim(regexp_replace(lower(unaccent(name)), '[^a-z0-9]+', ' ', 'g'))
    having count(*) = 1
)
update public.jobs as job
set company_id = company.id
from normalized_companies as company
where job.company_id is null
  and nullif(trim(job.company_name), '') is not null
  and trim(regexp_replace(lower(unaccent(job.company_name)), '[^a-z0-9]+', ' ', 'g')) = company.normalized_name;

-- Verification result: linked and unmatched rows.
select
    count(*) filter (where company_id is not null) as linked_jobs,
    count(*) filter (where company_id is null) as unmatched_jobs
from public.jobs;
