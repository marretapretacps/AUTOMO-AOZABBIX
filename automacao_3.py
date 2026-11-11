from datetime import datetime
import csv
import os
import re
import urllib.parse
from pyzabbix import ZabbixAPI

try:
    import pyperclip
    HAS_PYPERCLIP = True
except ImportError:
    HAS_PYPERCLIP = False

# ==============================================================================
# CONFIGURAÇÕES DO ZABBIX
# ==============================================================================
ZABBIX_URL = "http://zabbix.redeeduca.local/api_jsonrpc.php"
ZABBIX_TOKEN = "1adf1678ddcf8b6cf2cceae8c2f11ce1a51dc21f4baaddb7a9dd873fe76fa1b9"
# ==============================================================================


def conectar_zabbix():
    """Conecta ao servidor Zabbix via Token API."""
    try:
        zbx = ZabbixAPI(ZABBIX_URL)
        zbx.login(api_token=ZABBIX_TOKEN)
        return zbx
    except Exception as e:
        print(f"\n[!] Erro ao conectar ao Zabbix: {e}")
        return None


def limpar_tela():
    os.system("cls" if os.name == "nt" else "clear")


def converter_decimal_para_dms(lat_dec, lon_dec):
    """Converte latitude e longitude decimais para DMS (ex: 22°51'04.6\"S 47°06'19.6\"W)."""
    try:
        lat_dec, lon_dec = float(lat_dec), float(lon_dec)

        lat_dir = "S" if lat_dec < 0 else "N"
        lat_abs = abs(lat_dec)
        lat_g = int(lat_abs)
        lat_m_float = (lat_abs - lat_g) * 60
        lat_m = int(lat_m_float)
        lat_s = (lat_m_float - lat_m) * 60

        lon_dir = "W" if lon_dec < 0 else "E"
        lon_abs = abs(lon_dec)
        lon_g = int(lon_abs)
        lon_m_float = (lon_abs - lon_g) * 60
        lon_m = int(lon_m_float)
        lon_s = (lon_m_float - lon_m) * 60

        return (
            f"{lat_g:02d}°{lat_m:02d}'{lat_s:04.1f}\"{lat_dir} "
            f"{lon_g:02d}°{lon_m:02d}'{lon_s:04.1f}\"{lon_dir}"
        )
    except ValueError:
        return None


def obter_dados_localizacao(geo_zbx=""):
    """Obtém a localização automaticamente do Zabbix e converte para GMS (DMS)."""
    print("\n--- COORDENADAS / LOCALIZAÇÃO (TÉCNICO DE CAMPO) ---")
    entrada = geo_zbx.strip()

    if entrada:
        print(f"[✔] Coordenadas obtidas do Zabbix (original): {entrada}")
    else:
        print("[!] Host sem coordenadas cadastradas no Zabbix.")
        print("Cole as coordenadas decimais ou o link do Google Maps (Ex: -22.876042,-47.097768):")
        entrada = input("LOCALIZAÇÃO: ").strip()

    # Tenta extrair a latitude e longitude decimal da string recebida
    match = re.search(r"(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)", entrada)
    if match:
        lat_dec, lon_dec = match.group(1), match.group(2)
        geo_formatada = converter_decimal_para_dms(lat_dec, lon_dec)
        if geo_formatada:
            link_maps = f"https://www.google.com/maps?q={lat_dec},{lon_dec}"
            return geo_formatada, link_maps

    link_fallback = (
        f"https://www.google.com/maps?q={urllib.parse.quote(entrada)}" if entrada else ""
    )
    return entrada, link_fallback


def buscar_problema_no_zabbix():
    """Procura problemas ativos no Zabbix e puxa localização das tags ou do inventário do host."""
    zbx = conectar_zabbix()
    if not zbx:
        return {}

    termo_filtro = ""
    while True:
        print("\n[...] Consultando alertas ativos no Zabbix...")
        try:
            params = {
                "severities": [4, 5],
                "output": ["eventid", "objectid", "name", "clock"],
                "sortfield": "eventid",
                "sortorder": "DESC",
                "limit": 30,
            }

            problems = zbx.problem.get(**params)

            if not problems:
                print("[!] Nenhum alerta de alta severidade encontrado no Zabbix.")
                return {}

            trigger_ids = [p["objectid"] for p in problems if "objectid" in p]
            triggers_map = {}

            if trigger_ids:
                triggers = zbx.trigger.get(
                    triggerids=trigger_ids,
                    output=["triggerid"],
                    selectHosts=["hostid", "name"],
                    selectTags=["tag", "value"],
                )

                host_ids = [
                    h["hostid"] for t in triggers for h in t.get("hosts", [])
                ]
                hosts_inv_map = {}

                if host_ids:
                    hosts_data = zbx.host.get(
                        hostids=host_ids,
                        output=["hostid"],
                        selectInventory=["location_lat", "location_lon"],
                    )
                    for hd in hosts_data:
                        inv = hd.get("inventory")
                        if (
                            isinstance(inv, dict)
                            and inv.get("location_lat")
                            and inv.get("location_lon")
                        ):
                            hosts_inv_map[hd["hostid"]] = (
                                f"{inv['location_lat']},{inv['location_lon']}"
                            )

                for t in triggers:
                    hosts = t.get("hosts", [])
                    primeiro_host = next(iter(hosts), {})
                    host_id = primeiro_host.get("hostid", "")
                    host_name = primeiro_host.get("name", "Host Desconhecido")
                    tags = {
                        tg["tag"].lower(): tg["value"]
                        for tg in t.get("tags", [])
                    }

                    geo_encontrada = (
                        tags.get("geo", "")
                        or tags.get("coordenadas", "")
                        or tags.get("location", "")
                        or hosts_inv_map.get(host_id, "")
                    )

                    triggers_map[t["triggerid"]] = {
                        "host": host_name,
                        "pop": tags.get("pop", ""),
                        "geo": geo_encontrada,
                    }

            todos_problemas = []
            for prob in problems:
                trig_info = triggers_map.get(prob.get("objectid"), {})
                host_name = trig_info.get("host", "Host Desconhecido")
                data_evento = datetime.fromtimestamp(int(prob["clock"])).strftime("%d/%m/%Y %H:%M")
                
                item_dict = {
                    "host": host_name,
                    "evento": prob["name"],
                    "data_hora": data_evento,
                    "pop": trig_info.get("pop", ""),
                    "geo": trig_info.get("geo", ""),
                }

                if termo_filtro:
                    if (termo_filtro in host_name.lower()) or (termo_filtro in prob["name"].lower()):
                        todos_problemas.append(item_dict)
                else:
                    todos_problemas.append(item_dict)

            print("\n--- ALERTAS RECENTES NO ZABBIX ---")
            if termo_filtro:
                print(f"[Filtro Ativo: '{termo_filtro}']")

            lista_exibida = list(todos_problemas[:10])
            if not lista_exibida:
                print("[!] Nenhum alerta encontrado com este termo de busca.")
            else:
                for idx, item in enumerate(lista_exibida, 1):
                    print(f"({idx}) ({item['data_hora']}) {item['host']} -> {item['evento']}")

            print("\n(F) Pesquisar / Filtrar por Nome da Escola ou Problema")
            if termo_filtro:
                print("(R) Remover Filtro")
            print("(0) Inserir dados manualmente sem usar o Zabbix")

            escolha = input("\nSelecione o número do alerta, 'F' para pesquisar ou '0': ").strip()

            if escolha.upper() == "F":
                termo_filtro = input("Digite a escola ou problema para buscar: ").strip().lower()
            elif escolha.upper() == "R":
                termo_filtro = ""
            elif escolha.isdigit():
                num = int(escolha)
                if num == 0:
                    return {}
                if 0 < num <= len(lista_exibida):
                    return lista_exibida[num - 1]

        except Exception as e:
            print(f"[!] Erro ao buscar dados do Zabbix: {e}")
            return {}


def registrar_acionamento():
    print("\n--- REGISTRO DE ACIONAMENTO ---")

    dados_zbx = buscar_problema_no_zabbix()
    
    data_hora = dados_zbx.get("data_hora") or datetime.now().strftime("%d/%m/%Y %H:%M")
    host_zbx = dados_zbx.get("host", "")
    evento_zbx = dados_zbx.get("evento", "")
    pop_zbx = dados_zbx.get("pop", "")
    geo_zbx = dados_zbx.get("geo", "")

    if evento_zbx:
        print(f"\n[ ✔ ] Evento vindo do Zabbix: {evento_zbx}")
        evento = input("Confirme ou edite o EVENTO (ENTER para manter): ").strip() or evento_zbx
    else:
        evento = input("EVENTO (ex: POSSIVEL ROMPIMENTO / MASSIVA / ANEL): ").strip()

    evento_upper = evento.upper()
    is_massiva = "MASSIVA" in evento_upper
    is_anel = "ANEL" in evento_upper

    lista_escolas_str = ""
    escola_principal = ""

    if is_massiva or is_anel:
        print(f"\n--- OCORRÊNCIA MÚLTIPLA ({evento_upper}) ---")
        try:
            qtd = int(input("Quantas escolas/unidades fazem parte desta ocorrência? "))
        except ValueError:
            qtd = 1

        escolas_cadastradas = []
        for i in range(1, qtd + 1):
            padrao_esc = host_zbx if (i == 1 and host_zbx) else ""
            if padrao_esc:
                print(f"[ ✔ ] Escola {i} sugerida do Zabbix: {padrao_esc}")
            esc = input(f"Digite a ESCOLA {i} (ex: ED{i} - NOME DA ESCOLA): ").strip() or padrao_esc
            if esc:
                escolas_cadastradas.append(esc)

        escola_principal = " | ".join(escolas_cadastradas)
        lista_escolas_str = "\n".join([f"• {e}" for e in escolas_cadastradas])
    else:
        if host_zbx:
            print(f"[ ✔ ] Escola/Host vindo do Zabbix: {host_zbx}")
            escola_principal = input("Confirme ou edite a ESCOLA (ENTER para manter): ").strip() or host_zbx
        else:
                        escola_principal = input("ESCOLA (ex: ED158 - CEI PROFA MARIA...): ").strip()
        lista_escolas_str = f"• {escola_principal}"

    protocolo_ima = input("PROTOCOLO IMA (opcional, ENTER para deixar em branco): ").strip()
    rt = input("RT (opcional, ENTER para deixar em branco): ").strip().upper()
    
    if pop_zbx:
        print(f"[ ✔ ] POP vindo do Zabbix: {pop_zbx}")
        pop = input(f"POP (ENTER para '{pop_zbx}'): ").strip() or pop_zbx
    else:
        pop = input("POP (ex: 03): ").strip()

    geo, link = obter_dados_localizacao(geo_zbx)
    evidencias = input("EVIDÊNCIAS (ENTER para 'Monitoramento em tempo real'): ").strip() or "Monitoramento de rede"

    if is_massiva:
        mensagem_cliente = f"""# COMUNICADO DE INCIDENTE EM REDE #

Prezados,

Identificamos uma oscilação geral na região que afeta a conexão de internet das seguintes unidades escolares:

UNIDADES IMPACTADAS:
{lista_escolas_str}

• Horário da Ocorrência: {data_hora}
• Situação Atual: Nossas equipes de suporte e de campo já foram acionadas e estão trabalhando na localização e correção da falha para restabelecer o sinal o mais breve possível.

Manteremos todos informados sobre a evolução do atendimento."""

    elif is_anel:
        mensagem_cliente = f"""# COMUNICADO DE MANUTENÇÃO NA REDE #

Prezados,

Informamos que detectamos uma instabilidade na rota de transmissão responsável por atender o circuito das unidades abaixo:

UNIDADES ENVOLVIDAS:
{lista_escolas_str}

• Horário do Evento: {data_hora}
• Status: Nossos especialistas estão realizando as análises e intervenções necessárias para restabelecer a conectividade.

Seguimos acompanhando o caso até a solução definitiva."""

    else:
        mensagem_cliente = f"""# NOTIFICAÇÃO DE INSTABILIDADE DE INTERNET #

Prezados,

Identificamos uma indisponibilidade temporária na conexão de internet da seguinte unidade escolar:

• Unidade: {escola_principal}
• Horário de Registro: {data_hora}

Nossa equipe técnica já identificou a ocorrência e está atuando nas tratativas de reparo para a completa normalização dos serviços.

Seguimos à disposição para maiores esclarecimentos."""

    mensagem_tecnico = f"""#ACIONAMENTO TÉCNICO#
DATA/HORA: {data_hora}
EVENTO: {evento}
PROTOCOLO IMA: {protocolo_ima}
RT: {rt}
ESCOLA: {escola_principal}
POP: {pop}
LOCALIZAÇÃO: {geo}

{link}

EVIDÊNCIAS: {evidencias}"""

    texto_completo = f"{mensagem_cliente}\n\n" + "=" * 50 + f"\n\n{mensagem_tecnico}"

    exibir_e_salvar(
        texto_exibicao=texto_completo,
        msg_cliente=mensagem_cliente,
        msg_tecnico=mensagem_tecnico,
        tipo_evento="ACIONAMENTO",
        dados_csv={
            "Tipo": "ACIONAMENTO",
            "Data_Hora": data_hora,
            "Protocolo_RT": f"IMA: {protocolo_ima} | RT: {rt}" if protocolo_ima or rt else pop,
            "Escola_POP": escola_principal,
            "Detalhes": evento,
            "Evidencias": evidencias,
        },
    )


def registrar_encerramento():
    print("\n--- FORMULÁRIO DE ENCERRAMENTO ---")

    protocolo_ima = ""
    while not protocolo_ima:
        protocolo_ima = input("PROTOCOLO IMA: ").strip()

    rt = input("RT (ex: RT-12345): ").strip().upper()

    data_hora_fim = input("DATA/HORA FIM (ENTER para usar a hora atual): ").strip()
    if not data_hora_fim:
        data_hora_fim = datetime.now().strftime("%d/%m/%Y %H:%M")

    causa = input("CAUSA (ex: Rompimento de Fibra Optica por Terceiros): ").strip() or "Rompimento de Fibra Óptica"

    print("\nDESCRIÇÃO DA ATIVIDADE:")
    print("  (1) Lançado cabo de 24fo e inserido 2 CEO")
    print("  (2) Reorganização e fusão de fibra no DIO / CEO")
    print("  (3) Troca de patch cord e validação de sinal óptico")
    print("  (0) Outra (digitar manualmente)")
    opt_desc = input("Escolha uma opção ou digite: ").strip()

    if opt_desc == "1":
        descricao = "Lançado cabo de 24fo e inserido 2 CEO"
    elif opt_desc == "2":
        descricao = "Reorganização e fusão de fibra no DIO / CEO"
    elif opt_desc == "3":
        descricao = "Troca de patch cord e validação de sinal óptico"
    elif opt_desc == "0" or not opt_desc:
        descricao = input("Digite a DESCRIÇÃO DA ATIVIDADE: ").strip()
    else:
        descricao = opt_desc

    print("\nMATERIAL UTILIZADO:")
    print("  (1) Cabo FO 24FO, 2 CEO, Conectores LC/APC, Fusões")
    print("  (2) Cabo Drop Figura 8, Emendas Mecânicas, Ancoragens")
    print("  (0) Digitar manualmente")
    opt_mat = input("Escolha uma opção ou digite: ").strip()

    if opt_mat == "1":
        material = "Cabo FO 24FO, 2 CEO, Conectores LC/APC, Fusões"
    elif opt_mat == "2":
        material = "Cabo Drop Figura 8, Emendas Mecânicas, Ancoragens"
    elif opt_mat == "0" or not opt_mat:
        material = input("Digite o MATERIAL UTILIZADO: ").strip()
    else:
        material = opt_mat

    evidencias = input("EVIDÊNCIAS (ENTER para 'fotos da atividade com timestamp'): ").strip() or "fotos da atividade"

    encerramento_str = f"""# COMUNICADO DE NORMALIZAÇÃO DE SERVIÇO #

Informamos que a ocorrência técnica relatada abaixo foi totalmente concluída e os serviços de conectividade foram RESTABELECIDOS.

• Protocolo IMA: {protocolo_ima}
• Referência RT: {rt}
• Data/Hora da Conclusão: {data_hora_fim}
• Motivo da Indisponibilidade: {causa}

Serviço validado e funcionando normalmente."""

    exibir_e_salvar(
        texto_exibicao=encerramento_str,
        msg_cliente=encerramento_str,
        msg_tecnico="",
        tipo_evento="ENCERRAMENTO",
        dados_csv={
            "Tipo": "ENCERRAMENTO",
            "Data_Hora": data_hora_fim,
            "Protocolo_RT": f"IMA: {protocolo_ima} | RT: {rt}",
            "Escola_POP": "N/A",
            "Detalhes": f"Causa: {causa} | Desc: {descricao} | Mat: {material}",
            "Evidencias": evidencias,
        },
    )


def exibir_e_salvar(texto_exibicao, msg_cliente, msg_tecnico, tipo_evento, dados_csv):
    print(f"\n--- MENSAGEM DE {tipo_evento} GERADA ---")
    print(texto_exibicao)
    print("-" * 50)

    if HAS_PYPERCLIP and tipo_evento == "ACIONAMENTO":
        print("Opções de Cópia para a Área de Transferência:")
        print("  (1) Copiar Mensagem Informativa do CLIENTE")
        print("  (2) Copiar Dispatch do TÉCNICO")
        print("  (3) Copiar AMBAS")
        opt_copy = input("Escolha qual deseja copiar (padrão 1): ").strip() or "1"

        if opt_copy == "2":
            pyperclip.copy(msg_tecnico)
            print("[ ✔ ] Mensagem do TÉCNICO copiada para a área de transferência!")
        elif opt_copy == "3":
            pyperclip.copy(texto_exibicao)
            print("[ ✔ ] Ambas as mensagens copiadas para a área de transferência!")
        else:
            pyperclip.copy(msg_cliente)
            print("[ ✔ ] Mensagem Informativa do CLIENTE copiada para a área de transferência!")
    elif HAS_PYPERCLIP:
        pyperclip.copy(texto_exibicao)
        print("[ ✔ ] Texto copiado automaticamente para a área de transferência!")

    data_arquivo = datetime.now().strftime("%d-%m-%Y")
    nome_txt = f"historico_chamados_{data_arquivo}.txt"

    with open(nome_txt, "a", encoding="utf-8") as f:
        f.write(texto_exibicao + "\n\n" + "=" * 40 + "\n\n")

    print(f"[ ✔ ] Registro salvo no arquivo TXT: '{nome_txt}'")

    nome_csv = "relatorio_geral_chamados.csv"
    arquivo_existe = os.path.exists(nome_csv)
    headers = ["Tipo", "Data_Hora", "Protocolo_RT", "Escola_POP", "Detalhes", "Evidencias"]

    with open(nome_csv, "a", newline="", encoding="utf-8-sig") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=headers)
        if not arquivo_existe:
            writer.writeheader()
        writer.writerow(dados_csv)

    print(f"[ ✔ ] Registro exportado para a planilha: '{nome_csv}'\n")


def main():
    while True:
        limpar_tela()

        print("=========================================")
        print("   SISTEMA DE REGISTRO NOC + ZABBIX      ")
        print("=========================================")
        print("(1) Gerar ACIONAMENTO")
        print("(2) Gerar ENCERRAMENTO")
        print("(0) Sair")

        opcao = input("\nEscolha uma opção: ").strip()

        if opcao == "1":
            registrar_acionamento()
            input("\nPressione ENTER para voltar ao menu...")
        elif opcao == "2":
            registrar_encerramento()
            input("\nPressione ENTER para voltar ao menu...")
        elif opcao == "0":
            print("\nAplicação encerrada.")
            break
        else:
            print("\n[!] Opção inválida! Tente novamente.")
            input("\nPressione ENTER para continuar...")


if __name__ == "__main__":
    main()