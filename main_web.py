import flet as ft
import json
import os
import pdfplumber
import re
import numpy as np

# Nome do arquivo onde os dados ficarão salvos
ARQUIVO_DADOS = "dados_cr.json"
MARCADOR_FIM = "Totais: no período"
PADRAO_CODIGO = r"[A-Z]{3,4}\d{2,3}"
PADRAO_SITUACAO = r"\b(AP|RM|RFM|RF)\b"

def parse_int(value, default=0):
    try:
        return int(value)
    except (ValueError, TypeError):
        return default

def parse_float(value, default=0.0):
    try:
        return float(value)
    except (ValueError, TypeError):
        return default

class Disciplina:
    def __init__(self, on_delete, on_change, n_ini="", p_ini="", nt_ini=""):
        self.nome = ft.TextField(
            label="Disciplina",
            value=n_ini,
            expand=True,
            on_change=on_change
        )
        self.peso = ft.TextField(
            label="Créditos",
            value=p_ini,
            keyboard_type="number",
            on_change=on_change,
            width=110
        )
        self.nota = ft.TextField(
            label="Nota",
            value=nt_ini,
            keyboard_type="number",
            on_change=on_change,
            width=80
        )
        self.view = ft.Container(
            padding=10,
            border=ft.border.all(1, "grey300"),
            border_radius=10,
            content=ft.Column(
                controls=[
                    self.nome,
                    ft.Row(
                        controls=[self.peso, self.nota],
                        spacing=10
                    ),
                    ft.TextButton(
                        "Remover disciplina",
                        style=ft.ButtonStyle(color="red"),
                        on_click=lambda e: on_delete(self)
                    )
                ],
                spacing=10
            )
        )

def main(page: ft.Page):
    page.title = "Simulador de CR"
    page.scroll = "adaptive"
    page.padding = 15

    disciplinas = []

    # =================================================================
    # SISTEMA DE ARQUIVOS HÍBRIDO (WEB + DESKTOP/MOBILE)
    # =================================================================
    
    # 1. Quando o upload termina (SÓ RODA NA WEB)
    def on_upload_result(e: ft.FilePickerUploadEvent):
        if e.error:
            page.show_dialog(ft.SnackBar(ft.Text(f"Erro no upload: {e.error}"), bgcolor="red"))
            page.update()
            return
            
        # O arquivo foi salvo na pasta "uploads" do servidor do Render
        caminho_no_servidor = os.path.join("uploads", e.file_name)
        
        # Agora podemos ler!
        leitura_pdf(caminho_no_servidor)
        
        page.show_dialog(ft.SnackBar(ft.Text(f"Boletim processado: {e.file_name}"), bgcolor="green"))
        page.update()

    # 2. Quando o usuário escolhe o arquivo
    def on_file_picked(e: ft.FilePickerResultEvent):
        if not e.files:
            return # Cancelou
            
        arquivo = e.files[0]
        
        # Lógica de bifurcação: WEB vs NATIVO
        if page.web:
            # Na web, arquivo.path é None. Precisamos fazer upload.
            page.show_dialog(ft.SnackBar(ft.Text("Enviando arquivo para o servidor..."), bgcolor="blue"))
            page.update()
            
            # Gera URL de upload e envia
            upload_url = page.get_upload_url(arquivo.name, 600)
            picker.upload([
                ft.FilePickerUploadFile(
                    name=arquivo.name,
                    upload_url=upload_url
                )
            ])
        else:
            # No Android/PC, o arquivo.path existe. Lê direto.
            leitura_pdf(arquivo.path)
            page.show_dialog(ft.SnackBar(ft.Text(f"Arquivo aberto: {arquivo.name}"), bgcolor="green"))
            page.update()

    # 3. Criar o FilePicker (Componente invisível)
    picker = ft.FilePicker(
        on_result=on_file_picked,  # Dispara ao escolher
        on_upload=on_upload_result # Dispara ao terminar upload
    )
    
    # IMPORTANTE: Adicionar ao overlay da página
    page.overlay.append(picker)

    # =================================================================

    def salvar_tudo():
        dados = {
            "total_creditos": txt_total_creditos.value,
            "cr_atual": txt_cr_atual.value,
            "periodo_ingresso": txt_periodo.value,
            "lista_disciplinas": []
        }
        for d in disciplinas:
            dados["lista_disciplinas"].append({
                "nome": d.nome.value, 
                "peso": d.peso.value, 
                "nota": d.nota.value
            })
        
        try:
            with open(ARQUIVO_DADOS, "w", encoding="utf-8") as f:
                json.dump(dados, f, indent=4)
        except Exception as ex:
            print(f"Erro ao salvar: {ex}")

    def carregar_tudo():
        if not os.path.exists(ARQUIVO_DADOS):
            adicionar_disciplina()
            return
        try:
            with open(ARQUIVO_DADOS, "r", encoding="utf-8") as f:
                dados = json.load(f)
            txt_total_creditos.value = dados.get("total_creditos", "")
            txt_cr_atual.value = dados.get("cr_atual", "")
            txt_periodo.value = dados.get("periodo_ingresso", "")
            
            lista_salva = dados.get("lista_disciplinas", [])
            for item in lista_salva:
                adicionar_disciplina(dados=item)
            
            if not lista_salva:
                adicionar_disciplina()
            calcular_cr()
            
        except Exception as ex:
            print(f"Erro ao ler arquivo: {ex}")
            adicionar_disciplina()

    def on_change_geral(e=None):
        calcular_cr()
        salvar_tudo()

    txt_total_creditos = ft.TextField(
        label="Créditos Totais Acumulados",
        keyboard_type="number",
        on_change=on_change_geral
    )

    txt_cr_atual = ft.TextField(
        label="CR Acumulado Atual",
        keyboard_type="number",
        on_change=on_change_geral
    )
    
    txt_periodo = ft.TextField(
        label="Período de ingresso (Ex: 2020/1)",
        keyboard_type="number",
        on_change=on_change_geral
    )
    
    resultado = ft.Text(
        "Aguardando cálculo...",
        size=18,
        weight="bold"
    )
    
    lista = ft.Column(spacing=10)
    
    def leitura_pdf(PATH_BOLETIM):
        try:
            with pdfplumber.open(PATH_BOLETIM) as pdf:
                texto_completo = ""
                creditos_pdf = []
                notas_pdf = []
                for pagina in pdf.pages:
                    texto_completo += pagina.extract_text() + "\n"

                FRASE_FIXA = "Sistema de Seleção Unificada em:"
                padrao = fr"{FRASE_FIXA}\s*(\d{{4}}/\d)"
                marc_ini = re.findall(padrao, texto_completo)
                
                pos_inicio = 0
                if marc_ini:
                    pos_1 = texto_completo.find(marc_ini[0])
                    pos_inicio = texto_completo.find(marc_ini[0], pos_1 + 1)
                    if pos_inicio == -1: pos_inicio = 0 

                pos_fim = texto_completo.rfind(MARCADOR_FIM)
                if pos_fim == -1: pos_fim = len(texto_completo)

                texto_util = texto_completo[pos_inicio : pos_fim]
                linhas = texto_util.split('\n')

                for linha in linhas:
                    match_codigo = re.search(PADRAO_CODIGO, linha)
                    if match_codigo:
                        codigo = match_codigo.group()
                        
                        if not re.search(PADRAO_SITUACAO, linha): continue
                        if "*****" in linha: continue

                        linha_teste = linha.replace(codigo, "")
                        linha_teste = re.sub(r"\d{4}[./]\d", "", linha_teste)
                        if not re.search(r"\d", linha_teste): continue

                        linha_sem_data = re.sub(r"\d{4}[./]\d", "", linha)
                        linha_limpa = linha_sem_data.replace(codigo, "")
                        numeros = re.findall(r"[\d]+[.,]?\d*", linha_limpa)

                        if len(numeros) >= 2:
                            nota = numeros[-3].replace(",", ".")
                            credito = numeros[-5].replace(",", ".")
                            
                            notas_pdf.append(float(nota))
                            creditos_pdf.append(float(credito))
                
                soma_creditos = np.sum(np.array(creditos_pdf))
                txt_total_creditos.value = str(soma_creditos)
                
                if soma_creditos > 0:
                    numerador = np.sum(np.array(notas_pdf) * np.array(creditos_pdf))
                    txt_cr_atual_calculo = numerador / soma_creditos
                    txt_cr_atual.value = f"{txt_cr_atual_calculo:.4f}"
                
                page.update()
        except Exception as e:
            print(f"ERRO: {e}")
            page.show_dialog(ft.SnackBar(ft.Text(f"Erro ao ler PDF: {e}"), bgcolor="red"))
            page.update()

    def calcular_cr():
        total_antigo = parse_int(txt_total_creditos.value)
        cr_atual = parse_float(txt_cr_atual.value)
        soma = 0
        pesos = 0
        for d in disciplinas:
            peso = parse_int(d.peso.value)
            nota = parse_float(d.nota.value)
            if peso > 0:
                soma += peso * nota
                pesos += peso
        if total_antigo + pesos > 0:
            novo_cr = (total_antigo * cr_atual + soma) / (total_antigo + pesos)
        else:
            novo_cr = 0
        resultado.value = f"Novo CR Estimado: {novo_cr:.4f}"
        resultado.color = "green" if novo_cr >= cr_atual else "red"
        page.update()

    def adicionar_disciplina(e=None, dados=None):
        n = dados["nome"] if dados else ""
        p = dados["peso"] if dados else ""
        nt = dados["nota"] if dados else ""
        d = Disciplina(remover_disciplina, on_change_geral, n, p, nt)
        disciplinas.append(d)
        lista.controls.append(d.view)
        if e is not None:
            salvar_tudo()
            page.update()

    def remover_disciplina(d):
        disciplinas.remove(d)
        lista.controls.remove(d.view)
        on_change_geral()
        page.update()

    # --- APOIO / PIX ---
    chave_pix_copia_cola = "00020101021126580014br.gov.bcb.pix01364a063b34-f773-4f81-a183-b0c08e9ae4105204000053039865802BR5920GABRIEL A A DA SILVA6013RIO DE JANEIR62070503***6304A3B1"
    
    def fechar_pix(e):
        page.close(dlg_pix) # Atualizado para sintaxe nova

    async def copiar_pix(e):
        await ft.Clipboard().set(chave_pix_copia_cola)
        page.show_dialog(ft.SnackBar(ft.Text("Chave Pix copiada!"), bgcolor="green"))
        page.update()

    dlg_pix = ft.AlertDialog(
        title=ft.Text("Apoie o Projeto"),
        content=ft.Column([
            ft.Text("Ajude a manter o projeto ativo!"),
            ft.Text("Escaneie o QR Code ou copie a chave abaixo:", text_align="center"),
            ft.Container(
                content=ft.Image(
                    src="assets/pix.jpg", # Ajustado para pasta assets
                    width=300, 
                    height=300,
                    fit="contain"
                ),
                alignment=ft.Alignment.CENTER
            ),
            ft.TextField(
                value=chave_pix_copia_cola, 
                read_only=True, 
                text_size=12, 
                height=40,
                border_radius=10,
            )
        ], tight=True, width=600, height=500, alignment="center", scroll=ft.ScrollMode.ADAPTIVE),
        actions=[
            ft.TextButton("Fechar", on_click=fechar_pix),
            ft.FilledButton("Copiar Chave", icon=ft.Icons.COPY, on_click=copiar_pix),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )

    def abrir_modal_pix(e):
        page.open(dlg_pix) # Sintaxe nova
        page.update()

    btn_apoio = ft.FilledButton(
        "Apoiar", 
        icon=ft.Icons.VOLUNTEER_ACTIVISM, 
        style=ft.ButtonStyle(bgcolor=ft.Colors.PINK_400, color=ft.Colors.WHITE),
        on_click=abrir_modal_pix 
    )

    # Botão de Importar atualizado para chamar o picker correto
    btn_importar = ft.Button(
        content=ft.Row([ft.Icon(ft.Icons.UPLOAD_FILE), ft.Text("Importar Boletim")]),
        on_click=lambda _: picker.pick_files(allow_multiple=False, allowed_extensions=["pdf"])
    )

    page.add(
        ft.Row(controls=[ft.Text("Simulador de CR", size=24, weight="bold"), btn_apoio]),
        txt_total_creditos,
        txt_cr_atual,
        ft.Row(
            controls=[
                btn_importar, # Botão novo aqui
                ft.Text("Selecione o arquivo PDF do boletim")
            ]
        ),
        ft.FilledButton("Adicionar Disciplina", on_click=adicionar_disciplina),
        ft.Text("Disciplinas:", size=18),
        lista,
        ft.Container(
            content=resultado,
            padding=12,
            border_radius=10,
            border=ft.border.all(1, "grey300")
        )
    )
    
    carregar_tudo()
    page.update()

if __name__ == "__main__":
    if not os.path.exists("uploads"):
        os.makedirs("uploads")

    ft.app(
        target=main, 
        view=ft.AppView.WEB_BROWSER, 
        upload_dir="uploads",
        port=int(os.getenv("PORT", 8000)),
        host="0.0.0.0" 
    )
