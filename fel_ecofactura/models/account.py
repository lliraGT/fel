# -*- encoding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

from datetime import datetime
from lxml import etree
import base64
import logging
import zeep

class AccountMove(models.Model):
    _inherit = "account.move"

    pdf_fel = fields.Binary('PDF FEL', copy=False)
    pdf_fel_name = fields.Char('Nombre PDF FEL', default='pdf_fel.pdf', size=32)

    def _post(self, soft=True):
        if self.certificar():
            return super(AccountMove, self)._post(soft)
        else:
            return self.env['account.move']

    def post(self):
        if self.certificar():
            return super(AccountMove, self).post()
    
    def certificar(self):
        for factura in self:
            if factura.requiere_certificacion():

                if factura.error_pre_validacion():
                    return
                    
                factura.descuento_lineas()
                
                tipo_documento_fel = factura.journal_id.tipo_documento_fel
                tipo_interno_factura = factura.type if 'type' in factura.fields_get() else factura.move_type
                if tipo_documento_fel in ['FACT', 'FACM'] and tipo_interno_factura == 'out_refund':
                    tipo_documento_fel = 'NCRE'
                    
                moneda = "GTQ"
                if factura.currency_id.id != factura.company_id.currency_id.id:
                    moneda = "USD"
                
                nit_receptor = 'CF'
                tipo_receptor = '1'
                
                if factura.partner_id.vat:
                    nit_receptor = factura.partner_id.vat.replace('-','')
                if factura.partner_id.nit_facturacion_fel:
                    nit_receptor = factura.partner_id.nit_facturacion_fel.replace('-','')
                    
                if len(nit_receptor) > 10:
                    tipo_receptor = '2'
                if tipo_documento_fel == "FESP" and factura.partner_id.cui:
                    nit_receptor = factura.partner_id.cui
                    tipo_receptor = '2'
                if tipo_documento_fel in ["FESP", "FACT", "FCAM", "NCRE", "NDEB", "NABN"] and factura.partner_id.country_id and factura.partner_id.country_id.code != 'GT':
                    tipo_receptor = '3'
                    
                fecha = factura.invoice_date.strftime('%Y-%m-%d') if factura.invoice_date else fields.Date.context_today(self).strftime('%Y-%m-%d')

                stdTWS = etree.Element("stdTWS", xmlns="FEL")

                TrnEstNum = etree.SubElement(stdTWS, "TrnEstNum")
                TrnEstNum.text = str(factura.journal_id.codigo_establecimiento)
                TipTrnCod = etree.SubElement(stdTWS, "TipTrnCod")
                TipTrnCod.text = tipo_documento_fel
                TrnNum = etree.SubElement(stdTWS, "TrnNum")
                TrnNum.text = str(factura.id)
                TrnFec = etree.SubElement(stdTWS, "TrnFec")
                TrnFec.text = fecha
                MonCod = etree.SubElement(stdTWS, "MonCod")
                MonCod.text = moneda
                TrnBenConNIT = etree.SubElement(stdTWS, "TrnBenConNIT")
                TrnBenConNIT.text = nit_receptor
                TrnBenConEspecial = etree.SubElement(stdTWS, "TrnBenConEspecial")
                TrnBenConEspecial.text = tipo_receptor
                TrnExp = etree.SubElement(stdTWS, "TrnExp")
                TrnExp.text = "1" if factura.tipo_gasto == "importacion" else "0"
                TrnExento = etree.SubElement(stdTWS, "TrnExento")
                TrnExento.text = "1" if factura.frase_exento_fel else "0"
                TrnFraseTipo = etree.SubElement(stdTWS, "TrnFraseTipo")
                TrnFraseTipo.text = "4" if factura.frase_exento_fel else "0"
                TrnEscCod = etree.SubElement(stdTWS, "TrnEscCod")
                TrnEscCod.text = str(factura.frase_exento_fel) if factura.frase_exento_fel else "0"
                # TrnEFACECliCod = etree.SubElement(stdTWS, "TrnEFACECliCod")
                # TrnEFACECliCod.text = factura.partner_id.ref or "-"
                TrnEFACECliNom = etree.SubElement(stdTWS, "TrnEFACECliNom")
                TrnEFACECliNom.text = factura.partner_id.name
                TrnEFACECliDir = etree.SubElement(stdTWS, "TrnEFACECliDir")
                TrnEFACECliDir.text = (factura.partner_id.street or "")[0:140]
                TrnObs = etree.SubElement(stdTWS, "TrnObs")
                TrnObs.text = factura.motivo_fel or ""
                TrnEMail = etree.SubElement(stdTWS, "TrnEmail")
                if factura.partner_id.email:
                    TrnEMail.text = factura.partner_id.email
                TrnCampAd01 = etree.SubElement(stdTWS, "TrnCampAd01")
                TrnCampAd01.text = eval(factura.company_id.trncampad01_fel) if factura.company_id.trncampad01_fel else ""
                TrnCampAd02 = etree.SubElement(stdTWS, "TrnCampAd02")
                TrnCampAd02.text = eval(factura.company_id.trncampad02_fel) if factura.company_id.trncampad02_fel else ""
                TrnCampAd03 = etree.SubElement(stdTWS, "TrnCampAd03")
                TrnCampAd03.text = eval(factura.company_id.trncampad03_fel) if factura.company_id.trncampad03_fel else ""
                TrnCampAd04 = etree.SubElement(stdTWS, "TrnCampAd04")
                TrnCampAd04.text = eval(factura.company_id.trncampad04_fel) if factura.company_id.trncampad04_fel else ""
                TrnCampAd05 = etree.SubElement(stdTWS, "TrnCampAd05")
                TrnCampAd05.text = eval(factura.company_id.trncampad05_fel) if factura.company_id.trncampad05_fel else ""
                TrnCampAd06 = etree.SubElement(stdTWS, "TrnCampAd06")
                TrnCampAd06.text = eval(factura.company_id.trncampad06_fel) if factura.company_id.trncampad06_fel else ""
                TrnCampAd07 = etree.SubElement(stdTWS, "TrnCampAd07")
                TrnCampAd08 = etree.SubElement(stdTWS, "TrnCampAd08")
                TrnCampAd09 = etree.SubElement(stdTWS, "TrnCampAd09")
                TrnCampAd10 = etree.SubElement(stdTWS, "TrnCampAd10")
                TrnCampAd11 = etree.SubElement(stdTWS, "TrnCampAd11")
                TrnCampAd12 = etree.SubElement(stdTWS, "TrnCampAd12")
                TrnCampAd13 = etree.SubElement(stdTWS, "TrnCampAd13")
                TrnCampAd13.text = str(factura.partner_id.name)
                TrnCampAd14 = etree.SubElement(stdTWS, "TrnCampAd14")
                TrnCampAd14.text = "POR CHEQUÉ RECHAZADO SE COBRARÁ Q. 100.00 POR GASTOS ADMINISTRATIVOS"
                TrnCampAd15 = etree.SubElement(stdTWS, "TrnCampAd15")
                TrnCampAd16 = etree.SubElement(stdTWS, "TrnCampAd16")
                TrnCampAd17 = etree.SubElement(stdTWS, "TrnCampAd17")
                TrnCampAd18 = etree.SubElement(stdTWS, "TrnCampAd18")
                TrnCampAd19 = etree.SubElement(stdTWS, "TrnCampAd19")
                TrnCampAd20 = etree.SubElement(stdTWS, "TrnCampAd20")
                TrnCampAd21 = etree.SubElement(stdTWS, "TrnCampAd21")
                TrnCampAd22 = etree.SubElement(stdTWS, "TrnCampAd22")
                TrnCampAd23 = etree.SubElement(stdTWS, "TrnCampAd23")
                TrnCampAd24 = etree.SubElement(stdTWS, "TrnCampAd24")
                TrnCampAd25 = etree.SubElement(stdTWS, "TrnCampAd25")
                TrnCampAd26 = etree.SubElement(stdTWS, "TrnCampAd26")
                TrnCampAd27 = etree.SubElement(stdTWS, "TrnCampAd27")
                TrnCampAd28 = etree.SubElement(stdTWS, "TrnCampAd28")
                TrnCampAd29 = etree.SubElement(stdTWS, "TrnCampAd29")
                TrnCampAd30 = etree.SubElement(stdTWS, "TrnCampAd30")
                
                stdTWSD = etree.SubElement(stdTWS, "stdTWSD")

                num = 1
                for linea in factura.invoice_line_ids:
                    if linea.price_total == 0:
                        continue
                
                    precio_unitario = linea.price_unit
                    if tipo_documento_fel == "FESP":
                        precio_unitario = linea.price_unit

                    stdTWSDIt = etree.SubElement(stdTWSD, "stdTWS.stdTWSCIt.stdTWSDIt")

                    TrnLiNum = etree.SubElement(stdTWSDIt, "TrnLiNum")
                    TrnLiNum.text = str(num)
                    num += 1
                    TrnArtCod = etree.SubElement(stdTWSDIt, "TrnArtCod")
                    if linea.product_id.default_code:
                        TrnArtCod.text = linea.product_id.default_code
                    else:
                        TrnArtCod.text = str(linea.product_id.id)
                    TrnArtNom = etree.SubElement(stdTWSDIt, "TrnArtNom")
                    TrnArtNom.text = linea.name
                    TrnCan = etree.SubElement(stdTWSDIt, "TrnCan")
                    TrnCan.text = '{:.6f}'.format(linea.quantity)
                    TrnVUn = etree.SubElement(stdTWSDIt, "TrnVUn")
                    TrnVUn.text = '{:.6f}'.format(precio_unitario)
                    TrnUniMed = etree.SubElement(stdTWSDIt, "TrnUniMed")
                    TrnUniMed.text = linea.product_uom_id.name if linea.product_uom_id else "UNIDAD"
                    TrnVDes = etree.SubElement(stdTWSDIt, "TrnVDes")
                    TrnVDes.text = '{:.2f}'.format((precio_unitario * linea.quantity) *  ( linea.discount / 100 ))
                    TrnArtBienSer = etree.SubElement(stdTWSDIt, "TrnArtBienSer")
                    if linea.product_id.type == 'product':
                        TrnArtBienSer.text = "B"
                    else:
                        TrnArtBienSer.text = "S"
                    
                    impuesto_adicional_cod = "0"
                    impuesto_adicional_uni = "0"
                    for i in linea.tax_ids:
                        if i.tipo_impuesto_fel in ["TURISMO HOSPEDAJE", "TURISMO PASAJES"]:
                            impuesto_adicional_cod = "3"
                            impuesto_adicional_uni = "1"
                    
                    TrnArtImpAdiCod = etree.SubElement(stdTWSDIt, "TrnArtImpAdiCod")
                    TrnArtImpAdiCod.text = impuesto_adicional_cod
                    TrnArtImpAdiUniGrav = etree.SubElement(stdTWSDIt, "TrnArtImpAdiUniGrav")
                    TrnArtImpAdiUniGrav.text = impuesto_adicional_uni
                    TrnDetCampAd01 = etree.SubElement(stdTWSDIt, "TrnDetCampAdi01")
                    TrnDetCampAd02 = etree.SubElement(stdTWSDIt, "TrnDetCampAdi02")
                    TrnDetCampAd03 = etree.SubElement(stdTWSDIt, "TrnDetCampAdi03")
                    TrnDetCampAd04 = etree.SubElement(stdTWSDIt, "TrnDetCampAdi04")
                    TrnDetCampAd05 = etree.SubElement(stdTWSDIt, "TrnDetCampAdi05")

                if tipo_documento_fel == "FCAM":
                    stdTWSCam = etree.SubElement(stdTWS, "stdTWSCam")
                    stdTWSCamIt = etree.SubElement(stdTWSCam, "stdTWS.stdTWSCam.stdTWSCamIt")
                    TrnAbonoNum = etree.SubElement(stdTWSCamIt, "TrnAbonoNum")
                    TrnAbonoNum.text = "1"
                    TrnAbonoFecVen = etree.SubElement(stdTWSCamIt, "TrnAbonoFecVen")
                    TrnAbonoFecVen.text = str(factura.invoice_date_due)
                    TrnAbonoMonto = etree.SubElement(stdTWSCamIt, "TrnAbonoMonto")
                    TrnAbonoMonto.text = str(factura.amount_total)
                    
                if tipo_documento_fel in ["NCRE", "NDEB"]:
                    stdTWSCam = etree.SubElement(stdTWS, "stdTWSNota")
                    stdTWSCamIt = etree.SubElement(stdTWSCam, "stdTWS.stdTWSNota.stdTWSNotaIt")
                    TDFEPRegimenAntiguo = etree.SubElement(stdTWSCamIt, "TDFEPRegimenAntiguo")
                    TDFEPRegimenAntiguo.text = "0"
                    TDFEPAutorizacion = etree.SubElement(stdTWSCamIt, "TDFEPAutorizacion")
                    TDFEPAutorizacion.text = factura.factura_original_id.firma_fel if factura.factura_original_id else ""
                    TDFEPSerie = etree.SubElement(stdTWSCamIt, "TDFEPSerie")
                    TDFEPSerie.text = factura.factura_original_id.serie_fel if factura.factura_original_id else ""
                    TDFEPNumero = etree.SubElement(stdTWSCamIt, "TDFEPNumero")
                    TDFEPNumero.text = factura.factura_original_id.numero_fel if factura.factura_original_id else ""
                    TDFEPNumero = etree.SubElement(stdTWSCamIt, "TDFEPFecEmision")
                    TDFEPNumero.text = str(factura.factura_original_id.invoice_date.strftime('%Y-%m-%d')) if factura.factura_original_id else ""
                    
                if factura.tipo_gasto == "importacion":
                    stdTWSCam = etree.SubElement(stdTWS, "stdTWSExp")
                    stdTWSCamIt = etree.SubElement(stdTWSCam, "stdTWS.stdTWSExp.stdTWSExpIt")
                    NomConsigODest = etree.SubElement(stdTWSCamIt, "NomConsigODest")
                    NomConsigODest.text = factura.consignatario_fel.name if factura.consignatario_fel else "-"
                    DirConsigODest = etree.SubElement(stdTWSCamIt, "DirConsigODest")
                    DirConsigODest.text = factura.consignatario_fel.street or "-" if factura.consignatario_fel else "-"
                    # CodConsigODest = etree.SubElement(stdTWSCamIt, "CodConsigODest")
                    # CodConsigODest.text = factura.consignatario_fel.ref or "-" if factura.consignatario_fel else "-"
                    OtraRef = etree.SubElement(stdTWSCamIt, "OtraRef")
                    OtraRef.text = "-"
                    INCOTERM = etree.SubElement(stdTWSCamIt, "INCOTERM")
                    INCOTERM.text = factura.incoterm_fel or "-"
                    ExpNom = etree.SubElement(stdTWSCamIt, "ExpNom")
                    ExpNom.text = factura.exportador_fel.name if factura.exportador_fel else "-"
                    ExpCod = etree.SubElement(stdTWSCamIt, "ExpCod")
                    ExpCod.text = factura.exportador_fel.ref or "-" if factura.exportador_fel else "-"
                    LugarExpedicion = etree.SubElement(stdTWSCamIt, "LugarExpedicion")
                    LugarExpedicion.text = factura.lugar_expedicion_fel or "-"
                    PaisConsigODest = etree.SubElement(stdTWSCamIt, "PaisConsigODest")
                    PaisConsigODest.text = factura.consignatario_fel.country_id.name or "-" if factura.consignatario_fel else "-"

                xmls = etree.tostring(stdTWS, xml_declaration=True, encoding="UTF-8")
                logging.warn(xmls.decode('utf8'))

                wsdl = "https://www.facturaenlineagt.com/adocumento?wsdl"
                if factura.company_id.pruebas_fel:
                    wsdl = "http://pruebas.ecofactura.com.gt:8080/fel/adocumento?wsdl"
                client = zeep.Client(wsdl=wsdl)

                resultado = client.service.Execute(factura.company_id.vat, factura.company_id.usuario_fel, factura.company_id.clave_fel, factura.company_id.vat, xmls)
                logging.warn(resultado)
                resultadoBytes = bytes(bytearray(resultado, encoding='utf-8'))
                resultadoXML = etree.XML(resultadoBytes)

                if resultadoXML.xpath("/DTE"):
                    dte = resultadoXML.xpath("/DTE")
                    factura.firma_fel = dte[0].get("NumeroAutorizacion")
                    factura.serie_fel = dte[0].get("Serie")
                    factura.numero_fel = dte[0].get("Numero")
                    factura.pdf_fel = resultadoXML.xpath("/DTE/Pdf")[0].text
                    factura.documento_xml_fel = base64.b64encode(xmls)
                    factura.resultado_xml_fel = resultadoXML.xpath("/DTE/Xml")[0].text
                    factura.certificador_fel = "ecofactura"
                else:
                    factura.error_certificador(resultado)
                    return False

                return True

            else:
                return True
        
    def button_cancel(self):
        result = super(AccountMove, self).button_cancel()
        for factura in self:
            if factura.requiere_certificacion() and factura.firma_fel:
                
                wsdl = "https://www.facturaenlineagt.com/aanulacion?wsdl"
                if factura.company_id.pruebas_fel:
                    wsdl = "http://pruebas.ecofactura.com.gt:8080/fel/aanulacion?wsdl"
                client = zeep.Client(wsdl=wsdl)
                
                resultado = client.service.Execute(factura.company_id.vat, factura.company_id.usuario_fel, factura.company_id.clave_fel, factura.company_id.vat, factura.firma_fel, factura.motivo_fel)
                logging.warn(resultado)
                resultadoBytes = bytes(bytearray(resultado, encoding='utf-8'))
                resultadoXML = etree.XML(resultadoBytes)
                factura.pdf_fel = resultadoXML.xpath("/DTE/Pdf")[0].text
                logging.warn(resultado)
                
                if not resultadoXML.xpath("/DTE"):
                    raise ValidationError(resultado)
                                                
class AccountJournal(models.Model):
    _inherit = "account.journal"

class ResCompany(models.Model):
    _inherit = "res.company"

    usuario_fel = fields.Char('Usuario FEL')
    clave_fel = fields.Char('Clave FEL')
    pruebas_fel = fields.Boolean('Pruebas FEL')
    trncampad01_fel = fields.Char(string="TrnCampAd01 FEL")
    trncampad02_fel = fields.Char(string="TrnCampAd02 FEL")
    trncampad03_fel = fields.Char(string="TrnCampAd03 FEL")
    trncampad04_fel = fields.Char(string="TrnCampAd04 FEL")
    trncampad05_fel = fields.Char(string="TrnCampAd05 FEL")
    trncampad06_fel = fields.Char(string="TrnCampAd06 FEL")
