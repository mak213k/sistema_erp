    import streamlit as st
    import pandas as pd
    import gspread
    import time
    import re
    from datetime import datetime, date
    from streamlit_option_menu import option_menu
    import plotly.express as px

    # ==============================================================================
    # 1. CONFIGURAÇÃO INICIAL
    # ==============================================================================
    st.set_page_config(page_title="Gestão Integrada", page_icon="🏗️", layout="wide")

    # Estilo da Sidebar (Vermelho Solicitado)
    st.markdown("""
        <style>
            [data-testid="stSidebar"] { background-color: #f7240c !important; }
            [data-testid="stSidebar"] * { color: white !important; }
            .stButton>button { width: 100%; }
        </style>
    """, unsafe_allow_html=True)

    # ID DA SUA PLANILHA (A NOVA)
    PLANILHA_ID = "1SWOLYM6jP8sz0KFNjAf7RqX2mK7DMJF72WFJYl4xvlE"

    # ==============================================================================
    # 2. BACKEND (LÓGICA E DADOS)
    # ==============================================================================
    def retry_api(func):
        def wrapper(*args, **kwargs):
            for i in range(5):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if "429" in str(e) or "500" in str(e):
                        time.sleep((2 ** i) + 1)
                        continue
                    else:
                        raise e
            return func(*args, **kwargs)
        return wrapper

    @st.cache_resource
    def get_db():
        try:
            return gspread.service_account(filename="credentials.json").open_by_key(PLANILHA_ID)
        except Exception as e:
            st.error(f"Erro ao conectar: {e}")
            st.stop()

    @st.cache_resource
    def verificar_headers_uma_vez():
        try:
            sheet = get_db()
            # ESTRUTURA COMPLETA (IGUAL AO SEU BACKEND.PY)
            abas = {
                "servicos": ["id", "cliente", "art", "tipo", "status", "data_cadastro", "link_pdf", "descricao", "historico", "id_orcamento", "resp_tecnico", "status_relatorio", "data_correcao", "corrigido_por", "data_entrega", "particao_fisica"],
                "agenda": ["data_agendada", "horario_inicio", "horario_fim", "cliente", "tipo", "equipe", "carro", "placa", "status_agendamento", "resp_tecnico", "id_servico_ref"],
                "funcionarios": ["nome", "cargo"],
                "carros": ["modelo", "placa"],
                "orcamentos": ["id_visual", "cliente", "data_emissao", "rt", "quant", "tipo", "descricao", "status"],
                "clientes": ["nome", "cnpj_cpf", "Endereco", "Numero", "Bairro", "Cidade", "Estado", "contato"],
                "usuarios": ["username", "password", "name", "role"]
            }
            existing_ws = [ws.title for ws in sheet.worksheets()]
            for nome, headers in abas.items():
                if nome not in existing_ws:
                    ws = sheet.add_worksheet(nome, 100, len(headers))
                    ws.append_row(headers)
        except: pass

    @st.cache_data(ttl=5)
    def ler_tabela(nome_aba):
        @retry_api
        def _fetch():
            return pd.DataFrame(get_db().worksheet(nome_aba).get_all_records())
        try: return _fetch()
        except: return pd.DataFrame()

    def adicionar_item_bd(nome_aba, dados):
        @retry_api
        def _save():
            ws = get_db().worksheet(nome_aba)
            ws.append_row([str(d) for d in dados])
            return True
        try:
            if _save():
                ler_tabela.clear()
                return True
        except Exception as e:
            if "200" in str(e): 
                ler_tabela.clear()
                return True
            st.error(f"Erro ao salvar: {e}")
            return False

    def salvar_dataframe_completo(nome_aba, df_novo):
        @retry_api
        def _update():
            ws = get_db().worksheet(nome_aba)
            ws.clear()
            df_salvar = df_novo.fillna("").astype(str)
            ws.update([df_salvar.columns.values.tolist()] + df_salvar.values.tolist())
            return True
        try:
            if _update():
                ler_tabela.clear()
                return True
        except: return False

    def atualizar_status_orcamento(id_visual, novo_status):
        try:
            ws = get_db().worksheet("orcamentos")
            cell = ws.find(str(id_visual))
            if cell:
                # Coluna 8 é Status
                ws.update_cell(cell.row, 8, novo_status)
                ler_tabela.clear()
                return True
            return False
        except: return False

    def calcular_serial_excel(dt):
        if isinstance(dt, datetime): dt = dt.date()
        return (dt - date(1899, 12, 30)).days

    # ==============================================================================
    # 3. PÁGINAS (COM A LÓGICA RESTAURADA)
    # ==============================================================================

    def render_dashboard():
        st.title("📊 Visão Geral")
        if st.button("🔄 Atualizar"):
            ler_tabela.clear()
            st.rerun()

        df_s = ler_tabela("servicos")
        df_o = ler_tabela("orcamentos")

        k1, k2, k3 = st.columns(3)
        k1.metric("Total de Serviços", len(df_s) if not df_s.empty else 0)
        k2.metric("Relatórios Pendentes", len(df_s[df_s['status_relatorio'] == 'P/ DIGITAÇÃO']) if not df_s.empty else 0)
        k3.metric("Orçamentos Abertos", len(df_o[df_o['status'] == 'PENDENTE']) if not df_o.empty else 0)

        if not df_s.empty:
            st.markdown("---")
            c1, c2 = st.columns(2)
            with c1:
                st.caption("Serviços por Tipo")
                st.plotly_chart(px.bar(df_s, x='tipo'), use_container_width=True)
            with c2:
                st.caption("Status dos Relatórios")
                st.plotly_chart(px.pie(df_s, names='status_relatorio'), use_container_width=True)

    def render_orcamentos():
        st.title("📄 Emissão de Orçamentos")
        df_orc = ler_tabela("orcamentos")
        df_clientes = ler_tabela("clientes")
        TIPOS_SERVICO = ["Instalação", "Manutenção Preventiva", "Manutenção Corretiva", "Vistoria / Visita Técnica", "Laudo Técnico", "Projeto", "Consultoria", "Emergência"]

        col_form, col_view = st.columns([1, 1.5], gap="large")

        with col_form:
            with st.expander("➕ NOVO ORÇAMENTO", expanded=True):
                st.caption("1. Identificação do Cliente")
                cl_nome_final = None
                
                if not df_clientes.empty:
                    opts = df_clientes['nome'].unique().tolist()
                    cl_nome_final = st.selectbox("Buscar Cliente:", opts, index=None, placeholder="Selecione...")
                    
                    if cl_nome_final:
                        info = df_clientes[df_clientes['nome'] == cl_nome_final].iloc[0]
                        st.info(f"🏢 **{cl_nome_final}**\n\nCNPJ: {info.get('cnpj_cpf','')}")
                else:
                    st.warning("Cadastre clientes primeiro na aba Cadastros.")

                st.markdown("---")
                
                with st.form("form_orcamento"):
                    st.caption("2. Detalhes Técnicos")
                    c1, c2 = st.columns([1, 1.5])
                    dt_emissao = c1.date_input("Data Emissão", datetime.today())
                    tp_servico = c2.selectbox("Tipo", TIPOS_SERVICO)
                    
                    # LÓGICA ORIGINAL DE RT E QUANTIDADE
                    rt_auto = calcular_serial_excel(dt_emissao)
                    proxima_quant = 1
                    if not df_orc.empty:
                        df_hoje = df_orc[df_orc['data_emissao'] == dt_emissao.strftime("%d/%m/%Y")]
                        if not df_hoje.empty:
                            try: proxima_quant = int(pd.to_numeric(df_hoje['quant']).max()) + 1
                            except: pass
                    
                    st.caption(f"📌 **Referência RT:** `{rt_auto}` | **Seq:** `{proxima_quant}`")
                    desc = st.text_area("Descrição Técnica *")
                    
                    if st.form_submit_button("💾 Gerar Orçamento", type="primary"):
                        if not cl_nome_final or not desc:
                            st.error("Preencha cliente e descrição.")
                        else:
                            id_vis = f"{rt_auto}-{proxima_quant}-{dt_emissao.strftime('%d%m%Y')}"
                            # Colunas: id_visual, cliente, data_emissao, rt, quant, tipo, descricao, status
                            dados = [id_vis, cl_nome_final, dt_emissao.strftime("%d/%m/%Y"), str(rt_auto), str(proxima_quant), tp_servico, desc, "PENDENTE"]
                            if adicionar_item_bd("orcamentos", dados):
                                st.success(f"Orçamento {id_vis} Gerado!")
                                time.sleep(1)
                                st.rerun()

        with col_view:
            st.subheader("📂 Gestão de Propostas")
            if not df_orc.empty:
                filtro = st.pills("Status", ["TODOS", "PENDENTE", "APROVADO", "CONVERTIDO EM SERVIÇO", "CANCELADO"], default="TODOS")
                view = df_orc if filtro == "TODOS" else df_orc[df_orc['status'] == filtro]
                
                for i, r in view.iterrows():
                    icone = "🟢" if r['status'] == "APROVADO" else "⚪"
                    with st.expander(f"{icone} {r['id_visual']} | {r['cliente']}"):
                        st.write(f"**Escopo:** {r['descricao']}")
                        st.caption(f"Status: {r['status']}")
                        c1, c2, c3 = st.columns(3)
                        
                        if r['status'] == "PENDENTE":
                            if c1.button("✅ Aprovar", key=f"ap_{r['id_visual']}"):
                                atualizar_status_orcamento(r['id_visual'], "APROVADO")
                                st.rerun()
                            if c3.button("❌ Reprovar", key=f"rp_{r['id_visual']}"):
                                atualizar_status_orcamento(r['id_visual'], "CANCELADO")
                                st.rerun()
                        elif r['status'] == "APROVADO":
                            st.success("Pronto para virar serviço!")
                            if c3.button("↩️ Voltar", key=f"bk_{r['id_visual']}"):
                                atualizar_status_orcamento(r['id_visual'], "PENDENTE")
                                st.rerun()

    def render_novo_servico():
        st.title("🛠️ Cadastro de Serviço")
        df_orc = ler_tabela("orcamentos")
        df_serv = ler_tabela("servicos")
        TIPOS_SERVICO = ["Instalação", "Manutenção Preventiva", "Manutenção Corretiva", "Vistoria / Visita Técnica", "Laudo Técnico", "Projeto", "Consultoria", "Emergência"]

        col_form, col_view = st.columns([1, 1.5], gap="large")

        # Variáveis de estado
        c_val, d_val, t_val, id_orc = "", "", None, None
        
        with col_form:
            with st.expander("➕ ABRIR OS (POR ORÇAMENTO)", expanded=True):
                pendentes = df_orc[df_orc['status'] != 'CONVERTIDO EM SERVIÇO'] if not df_orc.empty else pd.DataFrame()
                
                sel = st.selectbox("Orçamento Aprovado:", [f"{r['id_visual']} | {r['cliente']}" for i,r in pendentes.iterrows()] if not pendentes.empty else [])
                
                if sel:
                    rid = sel.split(" | ")[0]
                    row = pendentes[pendentes['id_visual'] == rid].iloc[0]
                    c_val, d_val, t_val, id_orc = row['cliente'], row['descricao'], row['tipo'], rid
                    st.success(f"Orçamento {id_orc} selecionado.")
            
            with st.form("form_servico"):
                c1, c2 = st.columns([2, 1])
                c1.text_input("ID OS", value=id_orc, disabled=True)
                tipo = c2.selectbox("Tipo", TIPOS_SERVICO, index=TIPOS_SERVICO.index(t_val) if t_val in TIPOS_SERVICO else 0)
                st.text_input("Cliente", value=c_val, disabled=True)
                
                # LÓGICA DE ART DO SEU ARQUIVO ORIGINAL
                st.markdown("### Regularização (ART)")
                art_pendente = st.checkbox("🚩 Gerar com ART Pendente", value=False)
                c_uf, c_art = st.columns([1, 3])
                uf = c_uf.selectbox("UF", ["SP", "MG", "RJ"], disabled=art_pendente)
                num_art = c_art.text_input("Número ART", disabled=art_pendente)
                
                desc = st.text_area("Escopo", value=d_val)
                
                if st.form_submit_button("🚀 Gerar Ordem de Serviço", type="primary"):
                    if not id_orc: st.error("Selecione um orçamento.")
                    else:
                        # Lógica de validação ART
                        art_final = "PENDENTE"
                        if not art_pendente:
                            clean = re.sub(r'\D', '', num_art)
                            if len(clean) < 5: 
                                st.error("ART Inválida.")
                                st.stop()
                            art_final = f"{uf}-{clean}"
                        
                        # 16 COLUNAS EXATAS DO SEU BACKEND
                        ts = str(int(datetime.now().timestamp()))
                        dados = [
                            ts,                 # id
                            c_val,              # cliente
                            art_final,          # art
                            tipo,               # tipo
                            "PENDENTE",         # status
                            datetime.now().strftime("%d/%m/%Y %H:%M"), # data_cadastro
                            "Upload Off",       # link_pdf (placeholder)
                            desc,               # descricao
                            "Cadastro Inicial", # historico
                            id_orc,             # id_orcamento
                            "",                 # resp_tecnico
                            "-",                # status_relatorio
                            "",                 # data_correcao
                            "",                 # corrigido_por
                            "",                 # data_entrega
                            "-"                 # particao_fisica
                        ]
                        
                        if adicionar_item_bd("servicos", dados):
                            atualizar_status_orcamento(id_orc, "CONVERTIDO EM SERVIÇO")
                            st.success(f"OS Criada com ART {art_final}!")
                            time.sleep(1)
                            st.rerun()

        with col_view:
            st.subheader("📋 Serviços Recentes")
            if not df_serv.empty:
                st.dataframe(df_serv[['id_orcamento', 'cliente', 'art', 'status']], use_container_width=True, hide_index=True)

    def render_painel_tecnico():
        st.title("🔧 Painel Técnico")
        if st.button("🔄 Atualizar"): 
            ler_tabela.clear()
            st.rerun()

        df_s = ler_tabela("servicos")
        if df_s.empty: st.info("Sem dados."); return

        # Filtros
        st.markdown("### Fila de Relatórios")
        filtro = st.multiselect("Status", ["-", "P/ DIGITAÇÃO", "EM CORREÇÃO", "CORRIGIDO", "FINALIZADO"], default=["-", "P/ DIGITAÇÃO"])
        view = df_s[df_s['status_relatorio'].isin(filtro)].copy() if filtro else df_s

        # Editor com as colunas certas do seu backend
        edited = st.data_editor(
            view[['id', 'cliente', 'art', 'status_relatorio', 'link_pdf', 'resp_tecnico']],
            column_config={
                "id": st.column_config.TextColumn("ID", disabled=True),
                "cliente": st.column_config.TextColumn("Cliente", disabled=True),
                "status_relatorio": st.column_config.SelectboxColumn("Status", options=["-", "P/ DIGITAÇÃO", "EM CORREÇÃO", "CORRIGIDO", "FINALIZADO"]),
                "link_pdf": st.column_config.TextColumn("Link Drive/PDF")
            },
            use_container_width=True,
            hide_index=True,
            key="editor_painel"
        )

        if st.button("💾 Salvar Painel"):
            for i, row in edited.iterrows():
                idx = df_s[df_s['id'].astype(str) == str(row['id'])].index
                if not idx.empty:
                    df_s.at[idx[0], 'status_relatorio'] = row['status_relatorio']
                    df_s.at[idx[0], 'link_pdf'] = row['link_pdf']
                    df_s.at[idx[0], 'resp_tecnico'] = row['resp_tecnico']
            
            if salvar_dataframe_completo("servicos", df_s):
                st.success("Atualizado!")
                st.rerun()

    def render_cadastros():
        st.title("⚙️ Cadastros")
        tab1, tab2 = st.tabs(["Funcionários", "Clientes"])
        with tab1:
            df = ler_tabela("funcionarios")
            ed = st.data_editor(df, num_rows="dynamic", key="ed_func")
            if st.button("Salvar Equipe"): salvar_dataframe_completo("funcionarios", ed)
        with tab2:
            df = ler_tabela("clientes")
            ed = st.data_editor(df, num_rows="dynamic", key="ed_cli")
            if st.button("Salvar Clientes"): salvar_dataframe_completo("clientes", ed)

    # ==============================================================================
    # 4. MENU PRINCIPAL
    # ==============================================================================
    verificar_headers_uma_vez()

    with st.sidebar:
        st.title("Gestão")
        st.caption("ELizeu Lima, Davi Franças, Elizeu Lima")
        selection = option_menu(None, ["Dashboard", "Orçamentos", "Novo Serviço", "Painel Técnico", "Cadastros"], icons=["graph-up", "file-text", "plus-circle", "tools", "people"], default_index=0)

    if selection == "Dashboard": render_dashboard()
    elif selection == "Orçamentos": render_orcamentos()
    elif selection == "Novo Serviço": render_novo_servico()
    elif selection == "Painel Técnico": render_painel_tecnico()
    elif selection == "Cadastros": render_cadastros()