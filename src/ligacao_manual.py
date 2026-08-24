-- =====================================================================
-- Bloco 1 · Ligação Manual Justificada · Conciliação de Vendas
-- Grupo LLE · MVP-A
-- =====================================================================
-- Aplicação: Executar no SQL Editor do Supabase (uma vez).
-- Chave composta (adquirente, nsu, autorizacao) — mesma que
-- _chave_venda_original() do conciliacao_vendas.py. Uma ligação cobre
-- TODAS as parcelas da venda.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. TABELA PRINCIPAL
-- ---------------------------------------------------------------------
create table if not exists public.cv_ligacao_manual (
    id                bigserial primary key,

    -- Chave da venda (bate com _chave_venda_original)
    adquirente        text        not null,
    nsu               text        not null default '',
    autorizacao       text        not null default '',

    -- Referência opcional no Sankhya (texto livre)
    referencia_sankhya text,

    -- Justificativa obrigatória (mínimo 10 caracteres, validado no app)
    justificativa      text        not null,

    -- Contexto da venda no momento da ligação (para auditoria)
    venda_valor_total  numeric(14,2),
    venda_data         date,
    venda_bandeira     text,
    venda_modalidade   text,
    venda_parcelas     int,

    -- Autoria e ciclo de vida
    criado_por         text        not null,
    criado_em          timestamptz not null default now(),
    editado_por        text,
    editado_em         timestamptz,

    -- Soft-delete (histórico preservado para auditoria)
    ativo              boolean     not null default true,
    desfeito_por       text,
    desfeito_em        timestamptz,
    desfeito_motivo    text,

    constraint chk_justificativa_min
        check (char_length(justificativa) >= 10)
);

-- Chave lógica: 1 ligação ATIVA por venda
create unique index if not exists ux_cv_ligacao_ativa
    on public.cv_ligacao_manual (adquirente, nsu, autorizacao)
    where ativo = true;

-- Índice de busca por criador (para dashboards por usuário)
create index if not exists ix_cv_ligacao_criado_por
    on public.cv_ligacao_manual (criado_por, criado_em desc);


-- ---------------------------------------------------------------------
-- 2. TABELA DE AUDITORIA (histórico de mudanças)
-- ---------------------------------------------------------------------
create table if not exists public.cv_ligacao_manual_auditoria (
    id            bigserial primary key,
    ligacao_id    bigint      not null references public.cv_ligacao_manual(id) on delete cascade,
    acao          text        not null,   -- 'criacao', 'edicao', 'desfazer', 'restaurar'
    payload       jsonb,                  -- snapshot da alteração
    quem          text        not null,
    quando        timestamptz not null default now()
);

create index if not exists ix_cv_ligacao_aud_ligacao
    on public.cv_ligacao_manual_auditoria (ligacao_id, quando desc);


-- ---------------------------------------------------------------------
-- 3. TRIGGER de auditoria automática
-- ---------------------------------------------------------------------
create or replace function public.fn_cv_ligacao_auditoria()
returns trigger
language plpgsql
as $$
declare
    v_acao text;
    v_quem text;
begin
    if (TG_OP = 'INSERT') then
        v_acao := 'criacao';
        v_quem := NEW.criado_por;
        insert into public.cv_ligacao_manual_auditoria (ligacao_id, acao, payload, quem)
        values (NEW.id, v_acao, to_jsonb(NEW), v_quem);
        return NEW;
    end if;

    if (TG_OP = 'UPDATE') then
        -- Desfazer
        if OLD.ativo = true and NEW.ativo = false then
            v_acao := 'desfazer';
            v_quem := coalesce(NEW.desfeito_por, NEW.editado_por, NEW.criado_por);
        -- Restaurar (raro, mas possível)
        elsif OLD.ativo = false and NEW.ativo = true then
            v_acao := 'restaurar';
            v_quem := coalesce(NEW.editado_por, NEW.criado_por);
        -- Edição de conteúdo
        else
            v_acao := 'edicao';
            v_quem := coalesce(NEW.editado_por, NEW.criado_por);
        end if;
        insert into public.cv_ligacao_manual_auditoria (ligacao_id, acao, payload, quem)
        values (NEW.id, v_acao,
                jsonb_build_object('antes', to_jsonb(OLD), 'depois', to_jsonb(NEW)),
                v_quem);
        return NEW;
    end if;

    return NEW;
end;
$$;

drop trigger if exists tg_cv_ligacao_auditoria on public.cv_ligacao_manual;
create trigger tg_cv_ligacao_auditoria
    after insert or update on public.cv_ligacao_manual
    for each row execute function public.fn_cv_ligacao_auditoria();


-- ---------------------------------------------------------------------
-- 4. ROW-LEVEL SECURITY
-- ---------------------------------------------------------------------
alter table public.cv_ligacao_manual enable row level security;
alter table public.cv_ligacao_manual_auditoria enable row level security;

-- Ligacao manual: qualquer usuário autenticado pode ler
drop policy if exists p_cv_ligacao_select on public.cv_ligacao_manual;
create policy p_cv_ligacao_select
    on public.cv_ligacao_manual for select
    to authenticated
    using (true);

-- Insert: qualquer autenticado, mas precisa gravar seu próprio email em criado_por
drop policy if exists p_cv_ligacao_insert on public.cv_ligacao_manual;
create policy p_cv_ligacao_insert
    on public.cv_ligacao_manual for insert
    to authenticated
    with check (auth.email() is not null and criado_por = auth.email());

-- Update: qualquer autenticado (edição, desfazer) — quem edita é registrado
drop policy if exists p_cv_ligacao_update on public.cv_ligacao_manual;
create policy p_cv_ligacao_update
    on public.cv_ligacao_manual for update
    to authenticated
    using (true)
    with check (auth.email() is not null);

-- Auditoria: só leitura para autenticados; inserts feitos pelo trigger (bypass RLS)
drop policy if exists p_cv_ligacao_aud_select on public.cv_ligacao_manual_auditoria;
create policy p_cv_ligacao_aud_select
    on public.cv_ligacao_manual_auditoria for select
    to authenticated
    using (true);


-- ---------------------------------------------------------------------
-- 5. GRANTS explícitos (Supabase costuma exigir)
-- ---------------------------------------------------------------------
grant usage on schema public to authenticated;
grant select, insert, update on public.cv_ligacao_manual to authenticated;
grant usage, select on sequence public.cv_ligacao_manual_id_seq to authenticated;
grant select on public.cv_ligacao_manual_auditoria to authenticated;
grant usage, select on sequence public.cv_ligacao_manual_auditoria_id_seq to authenticated;


-- ---------------------------------------------------------------------
-- 6. VERIFICAÇÃO
-- ---------------------------------------------------------------------
-- Após executar, rodar:
--   select table_name from information_schema.tables
--   where table_schema = 'public' and table_name like 'cv_ligacao%';
-- Deve retornar 2 linhas: cv_ligacao_manual e cv_ligacao_manual_auditoria.
