# -*- encoding: utf-8 -*-

from odoo import models, fields, api, tools, _
from odoo.exceptions import UserError, ValidationError
from odoo.release import version_info

from lxml import etree, html
from datetime import datetime

import base64
import requests
import re
import json

import odoo.addons.l10n_gt_extra.a_letras as a_letras

#from OpenSSL import crypto
#import xmlsig
#from xades import XAdESContext, template, utils, ObjectIdentifier
#from xades.policy import GenericPolicyId, ImpliedPolicy

import logging
import re

class AccountMove(models.Model):
    _inherit = "account.move"

    firma_fel = fields.Char('Firma FEL', copy=False)
    serie_fel = fields.Char('Serie FEL', copy=False)
    numero_fel = fields.Char('Numero FEL', copy=False)
    numero_acceso_fel = fields.Char('Numero Acceso FEL', copy=False)
    factura_original_id = fields.Many2one('account.move', string="Factura original FEL", domain="[('invoice_date', '!=', False)]")
    consignatario_fel = fields.Many2one('res.partner', string="Consignatario o Destinatario FEL")
    comprador_fel = fields.Many2one('res.partner', string="Comprador FEL")
    exportador_fel = fields.Many2one('res.partner', string="Exportador FEL")
    lugar_expedicion_fel = fields.Char(string="Lugar Expedición FEL")
    incoterm_fel = fields.Char(string="Incoterm FEL")
    otra_referencia_fel = fields.Char(string="Otra Referencia FEL")
    frase_exento_fel = fields.Integer('Fase Exento FEL')
    motivo_fel = fields.Char(string='Motivo FEL')
    documento_xml_fel = fields.Binary('Documento XML FEL', copy=False)
    documento_xml_fel_name = fields.Char('Nombre documento XML FEL', default='documento_xml_fel.xml', size=32)
    resultado_xml_fel = fields.Binary('Resultado XML FEL', copy=False)
    resultado_xml_fel_name = fields.Char('Nombre resultado XML FEL', default='resultado_xml_fel.xml', size=32)
    certificador_fel = fields.Char('Certificador FEL', copy=False)
    
    def _get_invoice_reference_odoo_fel(self):
        """ Usa el numero FEL
        """
        return str(self.serie_fel) + '-' + str(self.numero_fel)

    def num_a_letras(self, amount):
        return a_letras.num_a_letras(amount,completo=True)

    def error_certificador(self, error):
        self.ensure_one()
        factura = self
        if factura.journal_id.error_en_historial_fel:
            factura.message_post(body='<p>No se publicó la factura por error del certificador FEL:</p> <p><strong>'+error+'</strong></p>')
        else:
            raise UserError('No se publicó la factura por error del certificador FEL: '+error)

    def requiere_certificacion(self, certificador=''):
        self.ensure_one()
        factura = self
        requiere = factura.is_invoice() and factura.journal_id.generar_fel and factura.amount_total != 0
        if certificador:
            requiere = requiere and ( factura.company_id.certificador_fel == certificador or not factura.company_id.certificador_fel )
        return requiere

    def error_pre_validacion(self):
        self.ensure_one()
        factura = self
        if factura.firma_fel:
            factura.error_certificador("La factura ya fue validada, por lo que no puede ser validada nuevamente")
            return True

        return False

    def descuento_lineas(self):
        self.ensure_one()
        factura = self

        precio_total_descuento = 0
        precio_total_positivo = 0

        # Guardar las descripciones, por que las modificaciones de los precios
        # y descuentos las reinician :(
        descr = {}
        nuevos_valores_lineas = []
        for linea in factura.invoice_line_ids:
            descr[linea.id] = linea.name

        for linea in factura.invoice_line_ids:
            if linea.price_total > 0:
                precio_total_positivo += linea.price_unit * linea.quantity
            elif linea.price_total < 0:
                precio_total_descuento += abs(linea.price_total)
                nuevos_valores_lineas.append([1, linea.id, { 'price_unit': 0 }])

        if precio_total_descuento > 0:
            por_descontar = precio_total_descuento
            for linea in factura.invoice_line_ids:
                if linea.price_total > 0:
                    descuento = (precio_total_descuento / precio_total_positivo) * 100 + linea.discount
                    if factura.journal_id.no_usar_descuento_fel:
                        nuevo_precio = (linea.price_unit * (100 - descuento) / 100)
                        nuevo_precio_total = tools.float_round(nuevo_precio * linea.quantity, precision_rounding=factura.currency_id.rounding, rounding_method='DOWN')

                        # Por los redondeos, es posible que queden centavos sin descontar;
                        # causando que la factura quede con un valor distinto al original.
                        # Éste calculo evita que esos centavos queden de mas.
                        # Solo funciona si la precisión decimal del precio del procuto es
                        # mayor o igual a 4.
                        descontado = linea.price_total - nuevo_precio_total
                        descontado = min(descontado, por_descontar)

                        por_descontar -= descontado
                        
                        # Si no se redondea antes de cambiar el precio de la linea, Odoo calcula los impuestos
                        # con el precio sin redondear, por lo que genera un valor erroneo.
                        precio_descontado = tools.float_round((linea.price_total - descontado) / linea.quantity, precision_digits=self.env['decimal.precision'].precision_get('Product Price'))
                        nuevos_valores_lineas.append([1, linea.id, { 'price_unit': precio_descontado, 'discount': 0 }])
                    else:
                        nuevos_valores_lineas.append([1, linea.id, { 'discount': descuento }])

            # Algunos módulos pasan skip_invoice_sync=True al confirmar facturas.
            # Eso causa problemas cuando modificamos los precios. Por ello, nosotros
            # siempre activamos la sincronizacion.
            factura.with_context(skip_invoice_sync=False).write({ 'invoice_line_ids': nuevos_valores_lineas })
            for linea in factura.invoice_line_ids:
                linea.name = descr[linea.id]

        return True

    def eliminar_etiquetas(self, texto_html):
        return html.fromstring(texto_html).text_content()

    def dte_documento(self):
        self.ensure_one()
        factura = self
        attr_qname = etree.QName("http://www.w3.org/2001/XMLSchema-instance", "schemaLocation")

        NSMAP = {
            "ds": "http://www.w3.org/2000/09/xmldsig#",
            "dte": "http://www.sat.gob.gt/dte/fel/0.2.0",
        }

        NSMAP_REF = {
            "cno": "http://www.sat.gob.gt/face2/ComplementoReferenciaNota/0.1.0",
        }

        NSMAP_ABONO = {
            "cfc": "http://www.sat.gob.gt/dte/fel/CompCambiaria/0.1.0",
        }

        NSMAP_EXP = {
            "cex": "http://www.sat.gob.gt/face2/ComplementoExportaciones/0.1.0",
        }

        NSMAP_FE = {
            "cfe": "http://www.sat.gob.gt/face2/ComplementoFacturaEspecial/0.1.0",
        }

        DTE_NS = "{http://www.sat.gob.gt/dte/fel/0.2.0}"
        DS_NS = "{http://www.w3.org/2000/09/xmldsig#}"
        CNO_NS = "{http://www.sat.gob.gt/face2/ComplementoReferenciaNota/0.1.0}"
        CFE_NS = "{http://www.sat.gob.gt/face2/ComplementoFacturaEspecial/0.1.0}"
        CEX_NS = "{http://www.sat.gob.gt/face2/ComplementoExportaciones/0.1.0}"
        CFC_NS = "{http://www.sat.gob.gt/dte/fel/CompCambiaria/0.1.0}"

        GTDocumento = etree.Element(DTE_NS+"GTDocumento", {}, Version="0.1", nsmap=NSMAP)
        SAT = etree.SubElement(GTDocumento, DTE_NS+"SAT", ClaseDocumento="dte")
        DTE = etree.SubElement(SAT, DTE_NS+"DTE", ID="DatosCertificados")
        DatosEmision = etree.SubElement(DTE, DTE_NS+"DatosEmision", ID="DatosEmision")

        tipo_documento_fel = factura.journal_id.tipo_documento_fel
        tipo_interno_factura = factura.type if 'type' in factura.fields_get() else factura.move_type
        if tipo_documento_fel in ['FACT', 'FACM'] and tipo_interno_factura == 'out_refund':
            tipo_documento_fel = 'NCRE'

        moneda = "GTQ"
        if factura.currency_id.id != factura.company_id.currency_id.id:
            moneda = "USD"

        fecha = factura.invoice_date.strftime('%Y-%m-%d') if factura.invoice_date else fields.Date.context_today(self).strftime('%Y-%m-%d')
        hora = "00:00:00-06:00"
        fecha_hora = fecha+'T'+hora
        numero_acceso = factura.numero_acceso_fel if factura.numero_acceso_fel else str(factura.id+100000000)
        DatosGenerales = etree.SubElement(DatosEmision, DTE_NS+"DatosGenerales", CodigoMoneda=moneda, FechaHoraEmision=fecha_hora, Tipo=tipo_documento_fel, NumeroAcceso=numero_acceso)
        if factura.tipo_gasto == 'importacion':
            DatosGenerales.attrib['Exp'] = 'SI'
        if factura.company_id.tipo_personeria_fel:
            DatosGenerales.attrib['TipoPersoneria'] = str(factura.company_id.tipo_personeria_fel)

        Emisor = etree.SubElement(DatosEmision, DTE_NS+"Emisor", AfiliacionIVA=factura.company_id.afiliacion_iva_fel or "GEN", CodigoEstablecimiento=str(factura.journal_id.codigo_establecimiento), CorreoEmisor=factura.company_id.email or '', NITEmisor=factura.company_id.vat.replace('-',''), NombreComercial=factura.journal_id.direccion.name, NombreEmisor=factura.company_id.name)
        DireccionEmisor = etree.SubElement(Emisor, DTE_NS+"DireccionEmisor")
        Direccion = etree.SubElement(DireccionEmisor, DTE_NS+"Direccion")
        Direccion.text = factura.journal_id.direccion.street or 'Ciudad'
        CodigoPostal = etree.SubElement(DireccionEmisor, DTE_NS+"CodigoPostal")
        CodigoPostal.text = factura.journal_id.direccion.zip or '01001'
        Municipio = etree.SubElement(DireccionEmisor, DTE_NS+"Municipio")
        Municipio.text = factura.journal_id.direccion.city or 'Guatemala'
        Departamento = etree.SubElement(DireccionEmisor, DTE_NS+"Departamento")
        Departamento.text = factura.journal_id.direccion.state_id.name if factura.journal_id.direccion.state_id else ''
        Pais = etree.SubElement(DireccionEmisor, DTE_NS+"Pais")
        Pais.text = factura.journal_id.direccion.country_id.code or 'GT'

        nit_receptor = 'CF'
        if factura.partner_id.vat:
            nit_receptor = factura.partner_id.vat.replace('-','')
        if factura.partner_id.nit_facturacion_fel:
            nit_receptor = factura.partner_id.nit_facturacion_fel.replace('-','')
        if tipo_documento_fel == "FESP" and factura.partner_id.cui:
            nit_receptor = factura.partner_id.cui
            
        Receptor = etree.SubElement(DatosEmision, DTE_NS+"Receptor", IDReceptor=nit_receptor, NombreReceptor=factura.partner_id.name if not factura.partner_id.parent_id else factura.partner_id.parent_id.name)
        
        if factura.partner_id.nombre_facturacion_fel:
            Receptor.attrib['NombreReceptor'] = factura.partner_id.nombre_facturacion_fel

        if factura.partner_id.email:
            Receptor.attrib['CorreoReceptor'] = factura.partner_id.email
            
        if len(nit_receptor) > 10:
            Receptor.attrib['TipoEspecial'] = "CUI"
        if tipo_documento_fel == "FESP" and factura.partner_id.cui:
            Receptor.attrib['TipoEspecial'] = "CUI"
        if factura.partner_id.country_id and factura.partner_id.country_id.code != 'GT':
            Receptor.attrib['TipoEspecial'] = "EXT"

        DireccionReceptor = etree.SubElement(Receptor, DTE_NS+"DireccionReceptor")
        Direccion = etree.SubElement(DireccionReceptor, DTE_NS+"Direccion")
        Direccion.text = " ".join([x for x in (factura.partner_id.street, factura.partner_id.street2) if x]).strip() or 'Ciudad'
        CodigoPostal = etree.SubElement(DireccionReceptor, DTE_NS+"CodigoPostal")
        CodigoPostal.text = factura.partner_id.zip or '01001'
        Municipio = etree.SubElement(DireccionReceptor, DTE_NS+"Municipio")
        Municipio.text = factura.partner_id.city or 'Guatemala'
        Departamento = etree.SubElement(DireccionReceptor, DTE_NS+"Departamento")
        Departamento.text = factura.partner_id.state_id.name if factura.partner_id.state_id else ''
        Pais = etree.SubElement(DireccionReceptor, DTE_NS+"Pais")
        Pais.text = factura.partner_id.country_id.code or 'GT'

        if 'dte:Frases' in factura.company_id.frases_fel:
            Frases = etree.fromstring(factura.company_id.frases_fel)
        else:
            Frases = etree.Element(DTE_NS+'Frases')
            def frase(tipo=0, escenario=0):
                etree.SubElement(Frases, DTE_NS+'Frase', TipoFrase=str(tipo), CodigoEscenario=str(escenario))
            exec(factura.company_id.frases_fel, {'etree': etree, 'Frases': Frases, 'DTE_NS': DTE_NS, 'factura': factura, 'frase': frase})
            
        if tipo_documento_fel in ['NABN', 'FESP', 'RECI', 'RDON']:
            frase_isr = Frases.find('.//*[@TipoFrase="1"]')
            if frase_isr is not None:
                Frases.remove(frase_isr)
            frase_iva = Frases.find('.//*[@TipoFrase="2"]')
            if frase_iva is not None:
                Frases.remove(frase_iva)
        DatosEmision.append(Frases)

        Items = etree.SubElement(DatosEmision, DTE_NS+"Items")

        linea_num = 0
        gran_subtotal = 0
        gran_total = 0
        gran_total_impuestos = 0
        gran_num_lineas_sin_impuestos = 0
        self.descuento_lineas()
        
        for linea in factura.invoice_line_ids:

            if linea.price_total == 0 and not factura.journal_id.enviar_lineas_en_cero_fel:
                continue

            linea_num += 1

            tipo_producto = "B"
            if linea.product_id.type == 'service':
                tipo_producto = "S"
            precio_unitario = linea.price_unit * (100-linea.discount) / 100
            precio_sin_descuento = linea.price_unit
            descuento = (precio_sin_descuento * linea.quantity) - (precio_unitario * linea.quantity)
            precio_unitario_base = precio_unitario
            if linea.price_total != linea.price_subtotal:
                precio_unitario_base = linea.price_subtotal / linea.quantity
            total_linea = precio_unitario * linea.quantity
            total_linea_base = precio_unitario_base * linea.quantity
            total_impuestos = total_linea - total_linea_base
            
            total_impuestos_extras = {}
            
            if len(linea.tax_ids) > 1:
                impuestos = linea.tax_ids.compute_all(precio_unitario, currency=factura.currency_id, quantity=linea.quantity, product=linea.product_id, partner=factura.partner_id)

                for i in impuestos['taxes']:
                    impuesto = self.env['account.tax'].browse(i['id'])
                    if impuesto.tipo_impuesto_fel:
                        if (impuesto.tipo_impuesto_fel not in total_impuestos_extras) and (not factura.currency_id.is_zero(i['amount'])):
                            total_impuestos_extras[impuesto.tipo_impuesto_fel] = {
                                'tipo': impuesto.tipo_impuesto_fel,
                                'codigo': impuesto.codigo_unidad_gravable_fel,
                                'total': i['amount'],
                                'base': i['base'],
                            }

                        if not impuesto.price_include:
                            total_linea += i['amount']
                        else:
                            total_impuestos -= i['amount']
                
            if factura.currency_id.is_zero(total_impuestos) and total_linea != 0:
                gran_num_lineas_sin_impuestos += 1

            Item = etree.SubElement(Items, DTE_NS+"Item", BienOServicio=tipo_producto, NumeroLinea=str(linea_num))
            Cantidad = etree.SubElement(Item, DTE_NS+"Cantidad")
            Cantidad.text = '{:.{p}f}'.format(linea.quantity, p=self.env['decimal.precision'].precision_get('Product Unit of Measure'))
            UnidadMedida = etree.SubElement(Item, DTE_NS+"UnidadMedida")
            UnidadMedida.text = linea.product_uom_id.name[0:3] if linea.product_uom_id else 'UNI'
            Descripcion = etree.SubElement(Item, DTE_NS+"Descripcion")
            Descripcion.text = linea.name
            PrecioUnitario = etree.SubElement(Item, DTE_NS+"PrecioUnitario")
            PrecioUnitario.text = '{:.6f}'.format(precio_sin_descuento)
            Precio = etree.SubElement(Item, DTE_NS+"Precio")
            Precio.text = '{:.6f}'.format(precio_sin_descuento * linea.quantity)
            Descuento = etree.SubElement(Item, DTE_NS+"Descuento")
            Descuento.text = '{:.6f}'.format(descuento)
            if tipo_documento_fel not in ['NABN', 'RECI', 'RDON', 'FPEQ']:
                Impuestos = etree.SubElement(Item, DTE_NS+"Impuestos")
                Impuesto = etree.SubElement(Impuestos, DTE_NS+"Impuesto")
                NombreCorto = etree.SubElement(Impuesto, DTE_NS+"NombreCorto")
                NombreCorto.text = "IVA"
                CodigoUnidadGravable = etree.SubElement(Impuesto, DTE_NS+"CodigoUnidadGravable")
                CodigoUnidadGravable.text = "1"
                if factura.currency_id.is_zero(total_impuestos) and total_linea != 0:
                    CodigoUnidadGravable.text = "2"
                MontoGravable = etree.SubElement(Impuesto, DTE_NS+"MontoGravable")
                MontoGravable.text = '{:.6f}'.format(total_linea_base)
                MontoImpuesto = etree.SubElement(Impuesto, DTE_NS+"MontoImpuesto")
                MontoImpuesto.text = '{:.6f}'.format(total_impuestos)
                for impuesto in total_impuestos_extras.values():
                    Impuesto = etree.SubElement(Impuestos, DTE_NS+"Impuesto")
                    NombreCorto = etree.SubElement(Impuesto, DTE_NS+"NombreCorto")
                    NombreCorto.text = impuesto['tipo']
                    CodigoUnidadGravable = etree.SubElement(Impuesto, DTE_NS+"CodigoUnidadGravable")
                    CodigoUnidadGravable.text = str(impuesto['codigo'])
                    if impuesto['tipo'] != 'PETROLEO':
                        MontoGravable = etree.SubElement(Impuesto, DTE_NS+"MontoGravable")
                        MontoGravable.text = '{:.6f}'.format(impuesto['total'])
                    else:
                        CantidadUnidadesGravables = etree.SubElement(Impuesto, DTE_NS+"CantidadUnidadesGravables")
                        CantidadUnidadesGravables.text = '{:.{p}f}'.format(linea.quantity, p=self.env['decimal.precision'].precision_get('Product Unit of Measure'))
                    MontoImpuesto = etree.SubElement(Impuesto, DTE_NS+"MontoImpuesto")
                    MontoImpuesto.text = '{:.6f}'.format(impuesto['total'])
                    
            Total = etree.SubElement(Item, DTE_NS+"Total")
            Total.text = '{:.6f}'.format(total_linea)

            gran_total += total_linea
            gran_subtotal += total_linea_base
            gran_total_impuestos += total_impuestos

        Totales = etree.SubElement(DatosEmision, DTE_NS+"Totales")
        if tipo_documento_fel not in ['NABN', 'RECI', 'RDON', 'FPEQ']:
            TotalImpuestos = etree.SubElement(Totales, DTE_NS+"TotalImpuestos")
            TotalImpuesto = etree.SubElement(TotalImpuestos, DTE_NS+"TotalImpuesto", NombreCorto="IVA", TotalMontoImpuesto='{:.6f}'.format(gran_total_impuestos))
            for impuesto in total_impuestos_extras.values():
                TotalImpuestoExtra = etree.SubElement(TotalImpuestos, DTE_NS+"TotalImpuesto", NombreCorto=impuesto['tipo'], TotalMontoImpuesto='{:.6f}'.format(impuesto['total']))
        GranTotal = etree.SubElement(Totales, DTE_NS+"GranTotal")
        GranTotal.text = '{:.6f}'.format(gran_total)

        # Si no hay frase de exenta de iva configurada en la compañia, poner el escenario ingresado en frase_exento_fel
        if Frases.find('.//*[@TipoFrase="4"]') is None:
            if tipo_documento_fel not in ['NABN', 'FESP'] and (factura.company_id.afiliacion_iva_fel or 'GEN') != 'PEQ' and gran_num_lineas_sin_impuestos > 0:
                Frase = etree.SubElement(Frases, DTE_NS+"Frase", CodigoEscenario=str(factura.frase_exento_fel) if factura.frase_exento_fel else "1", TipoFrase="4")

        if factura.company_id.adenda_fel:
            Adenda = etree.SubElement(SAT, DTE_NS+"Adenda")
            exec(factura.company_id.adenda_fel, {'etree': etree, 'Adenda': Adenda, 'factura': factura})

        # En todos estos casos, es necesario enviar complementos
        if tipo_documento_fel in ['NDEB', 'NCRE'] or tipo_documento_fel in ['FCAM'] or (tipo_documento_fel in ['FACT', 'FCAM'] and factura.tipo_gasto == 'importacion') or tipo_documento_fel in ['FESP']:
            Complementos = etree.SubElement(DatosEmision, DTE_NS+"Complementos")

            if tipo_documento_fel in ['NDEB', 'NCRE']:
                Complemento = etree.SubElement(Complementos, DTE_NS+"Complemento", IDComplemento="ReferenciasNota", NombreComplemento="Nota de Credito" if tipo_documento_fel == 'NCRE' else "Nota de Debito", URIComplemento="http://www.sat.gob.gt/face2/ComplementoReferenciaNota/0.1.0")
                if factura.factura_original_id.numero_fel:
                    ReferenciasNota = etree.SubElement(Complemento, CNO_NS+"ReferenciasNota", FechaEmisionDocumentoOrigen=str(factura.factura_original_id.invoice_date), MotivoAjuste=factura.motivo_fel or '-', NumeroAutorizacionDocumentoOrigen=factura.factura_original_id.firma_fel, NumeroDocumentoOrigen=factura.factura_original_id.numero_fel, SerieDocumentoOrigen=factura.factura_original_id.serie_fel, Version="0.0", nsmap=NSMAP_REF)
                elif factura.factura_original_id and factura.factura_original_id.ref and len(factura.factura_original_id.ref.split("-")) > 1:
                    ReferenciasNota = etree.SubElement(Complemento, CNO_NS+"ReferenciasNota", RegimenAntiguo="Antiguo", FechaEmisionDocumentoOrigen=str(factura.factura_original_id.invoice_date), MotivoAjuste=factura.motivo_fel or '-', NumeroAutorizacionDocumentoOrigen=factura.factura_original_id.firma_fel, NumeroDocumentoOrigen=factura.factura_original_id.ref.split("-")[1], SerieDocumentoOrigen=factura.factura_original_id.ref.split("-")[0], Version="0.0", nsmap=NSMAP_REF)

            if tipo_documento_fel in ['FCAM']:
                Complemento = etree.SubElement(Complementos, DTE_NS+"Complemento", IDComplemento="FCAM", NombreComplemento="AbonosFacturaCambiaria", URIComplemento="http://www.sat.gob.gt/dte/fel/CompCambiaria/0.1.0")
                AbonosFacturaCambiaria = etree.SubElement(Complemento, CFC_NS+"AbonosFacturaCambiaria", Version="1", nsmap=NSMAP_ABONO)
                Abono = etree.SubElement(AbonosFacturaCambiaria, CFC_NS+"Abono")
                NumeroAbono = etree.SubElement(Abono, CFC_NS+"NumeroAbono")
                NumeroAbono.text = "1"
                FechaVencimiento = etree.SubElement(Abono, CFC_NS+"FechaVencimiento")
                FechaVencimiento.text = str(factura.invoice_date_due)
                MontoAbono = etree.SubElement(Abono, CFC_NS+"MontoAbono")
                MontoAbono.text = '{:.3f}'.format(gran_total)

            if tipo_documento_fel in ['FACT', 'FCAM'] and factura.tipo_gasto == 'importacion':
                Complemento = etree.SubElement(Complementos, DTE_NS+"Complemento", IDComplemento="text", NombreComplemento="text", URIComplemento="http://www.sat.gob.gt/face2/ComplementoExportaciones/0.1.0")
                Exportacion = etree.SubElement(Complemento, CEX_NS+"Exportacion", Version="1", nsmap=NSMAP_EXP)
                LugarExpedicion = etree.SubElement(Exportacion, CEX_NS+"LugarExpedicion")
                LugarExpedicion.text = factura.lugar_expedicion_fel or "-"
                NombreConsignatarioODestinatario = etree.SubElement(Exportacion, CEX_NS+"NombreConsignatarioODestinatario")
                NombreConsignatarioODestinatario.text = factura.consignatario_fel.name if factura.consignatario_fel else "-"
                DireccionConsignatarioODestinatario = etree.SubElement(Exportacion, CEX_NS+"DireccionConsignatarioODestinatario")
                DireccionConsignatarioODestinatario.text = factura.consignatario_fel.street or "-" if factura.consignatario_fel else "-"
                PaisConsignatario = etree.SubElement(Exportacion, CEX_NS+"PaisConsignatario")
                PaisConsignatario.text = factura.consignatario_fel.country_id.name or "-" if factura.consignatario_fel else "-"
                OtraReferencia = etree.SubElement(Exportacion, CEX_NS+"OtraReferencia")
                OtraReferencia.text = factura.otra_referencia_fel or "-"
                if len(factura.invoice_line_ids.filtered(lambda l: l.product_id.type != 'service')) > 0:
                    INCOTERM = etree.SubElement(Exportacion, CEX_NS+"INCOTERM")
                    INCOTERM.text = factura.incoterm_fel or "-"
                NombreExportador = etree.SubElement(Exportacion, CEX_NS+"NombreExportador")
                NombreExportador.text = factura.exportador_fel.name if factura.exportador_fel else "-"
                CodigoExportador = etree.SubElement(Exportacion, CEX_NS+"CodigoExportador")
                CodigoExportador.text = factura.exportador_fel.ref or "-" if factura.exportador_fel else "-"

            if tipo_documento_fel in ['FESP']:
                total_isr = abs(factura.amount_tax)

                total_iva_retencion = 0
                
                # Version 13, 14
                if 'amount_by_group' in factura.fields_get():
                    for impuesto in factura.amount_by_group:
                        if impuesto[1] > 0:
                            total_iva_retencion += impuesto[1]

                # Version 15, 16
                if 'tax_totals_json' in factura.fields_get() or 'tax_totals' in factura.fields_get():
                    invoice_totals = json.loads(factura.tax_totals_json) if 'tax_totals_json' in factura.fields_get() else factura.tax_totals
                    for grupos in invoice_totals['groups_by_subtotal'].values():
                        for impuesto in grupos:
                            if impuesto['tax_group_amount'] > 0:
                                total_iva_retencion += impuesto['tax_group_amount']

                Complemento = etree.SubElement(Complementos, DTE_NS+"Complemento", IDComplemento="FacturaEspecial", NombreComplemento="FacturaEspecial", URIComplemento="http://www.sat.gob.gt/face2/ComplementoFacturaEspecial/0.1.0")
                RetencionesFacturaEspecial = etree.SubElement(Complemento, CFE_NS+"RetencionesFacturaEspecial", Version="1", nsmap=NSMAP_FE)
                RetencionISR = etree.SubElement(RetencionesFacturaEspecial, CFE_NS+"RetencionISR")
                RetencionISR.text = '{:.3f}'.format(total_isr)
                RetencionIVA = etree.SubElement(RetencionesFacturaEspecial, CFE_NS+"RetencionIVA")
                RetencionIVA.text = '{:.3f}'.format(total_iva_retencion)
                TotalMenosRetenciones = etree.SubElement(RetencionesFacturaEspecial, CFE_NS+"TotalMenosRetenciones")
                TotalMenosRetenciones.text = '{:.3f}'.format(factura.amount_total)
                
        if Frases is not None and len(Frases) == 0:
            DatosEmision.remove(Frases)

        # signature = xmlsig.template.create(
        #     xmlsig.constants.TransformInclC14N,
        #     xmlsig.constants.TransformRsaSha256,
        #     "Signature"
        # )
        # signature_id = utils.get_unique_id()
        # ref_datos = xmlsig.template.add_reference(
        #     signature, xmlsig.constants.TransformSha256, uri="#DatosEmision"
        # )
        # xmlsig.template.add_transform(ref_datos, xmlsig.constants.TransformEnveloped)
        # ref_prop = xmlsig.template.add_reference(
        #     signature, xmlsig.constants.TransformSha256, uri_type="http://uri.etsi.org/01903#SignedProperties", uri="#" + signature_id
        # )
        # xmlsig.template.add_transform(ref_prop, xmlsig.constants.TransformInclC14N)
        # ki = xmlsig.template.ensure_key_info(signature)
        # data = xmlsig.template.add_x509_data(ki)
        # xmlsig.template.x509_data_add_certificate(data)
        # xmlsig.template.x509_data_add_subject_name(data)
        # serial = xmlsig.template.x509_data_add_issuer_serial(data)
        # xmlsig.template.x509_issuer_serial_add_issuer_name(serial)
        # xmlsig.template.x509_issuer_serial_add_serial_number(serial)
        # qualifying = template.create_qualifying_properties(
        #     signature, name=utils.get_unique_id()
        # )
        # props = template.create_signed_properties(
        #     qualifying, name=signature_id, datetime=fecha_hora
        # )
        #
        # GTDocumento.append(signature)
        # ctx = XAdESContext()
        # with open(path.join("/home/odoo/megaprint_leplan", "51043491-6747a80bb6a554ae.pfx"), "rb") as key_file:
        #     ctx.load_pkcs12(crypto.load_pkcs12(key_file.read(), "Planeta123$"))
        # ctx.sign(signature)
        # ctx.verify(signature)
        # DatosEmision.remove(SingatureTemp)

        # xml_con_firma = etree.tostring(GTDocumento, encoding="utf-8").decode("utf-8")
                
        return GTDocumento

    def dte_anulacion(self):
        self.ensure_one()
        factura = self

        NSMAP = {
            "ds": "http://www.w3.org/2000/09/xmldsig#",
            "dte": "http://www.sat.gob.gt/dte/fel/0.1.0",
        }

        DTE_NS = "{http://www.sat.gob.gt/dte/fel/0.1.0}"
        DS_NS = "{http://www.w3.org/2000/09/xmldsig#}"
    
        tipo_documento_fel = factura.journal_id.tipo_documento_fel
        tipo_interno_factura = factura.type if 'type' in factura.fields_get() else factura.move_type
        if tipo_documento_fel in ['FACT', 'FACM'] and tipo_interno_factura == 'out_refund':
            tipo_documento_fel = 'NCRE'

        nit_receptor = 'CF'
        if factura.partner_id.vat:
            nit_receptor = factura.partner_id.vat.replace('-','')
        if tipo_documento_fel == "FESP" and factura.partner_id.cui:
            nit_receptor = factura.partner_id.cui

        fecha = fields.Date.from_string(factura.invoice_date).strftime('%Y-%m-%d')
        hora = "00:00:00-06:00"
        fecha_hora = fecha+'T'+hora
        
        fecha_hoy_hora = fields.Date.context_today(factura).strftime('%Y-%m-%dT%H:%M:%S')

        GTAnulacionDocumento = etree.Element(DTE_NS+"GTAnulacionDocumento", {}, Version="0.1", nsmap=NSMAP)
        SAT = etree.SubElement(GTAnulacionDocumento, DTE_NS+"SAT")
        AnulacionDTE = etree.SubElement(SAT, DTE_NS+"AnulacionDTE", ID="DatosCertificados")
        DatosGenerales = etree.SubElement(AnulacionDTE, DTE_NS+"DatosGenerales", ID="DatosAnulacion", NumeroDocumentoAAnular=factura.firma_fel, NITEmisor=factura.company_id.vat.replace("-",""), IDReceptor=nit_receptor, FechaEmisionDocumentoAnular=fecha_hora, FechaHoraAnulacion=fecha_hoy_hora, MotivoAnulacion=factura.motivo_fel or '-')
        
        return GTAnulacionDocumento

class AccountJournal(models.Model):
    _inherit = "account.journal"

    generar_fel = fields.Boolean('Generar FEL')
    tipo_documento_fel = fields.Selection([('FACT', 'FACT'), ('FCAM', 'FCAM'), ('FPEQ', 'FPEQ'), ('FCAP', 'FCAP'), ('FESP', 'FESP'), ('NABN', 'NABN'), ('RDON', 'RDON'), ('RECI', 'RECI'), ('NDEB', 'NDEB'), ('NCRE', 'NCRE')], 'Tipo de Documento FEL', copy=False)
    error_en_historial_fel = fields.Boolean('Error FEL en historial', help='Los errores no se muestran en pantalla, solo se registran en el historial')
    contingencia_fel = fields.Boolean('Habilitar contingencia FEL')
    invoice_reference_type = fields.Selection(selection_add=[('fel', 'FEL')], ondelete=({'fel': 'set default'} if version_info[0] > 13 else ''))
    no_usar_descuento_fel = fields.Boolean('No usar descuento cuando hay lineas negativas en FEL')
    enviar_lineas_en_cero_fel = fields.Boolean('Enviar lineas en cero para FEL')

class AccountTax(models.Model):
    _inherit = 'account.tax'

    tipo_impuesto_fel = fields.Selection([('IVA', 'IVA'), ('PETROLEO', 'PETROLEO'), ('TURISMO HOSPEDAJE', 'TURISMO HOSPEDAJE'), ('TURISMO PASAJES', 'TURISMO PASAJES'), ('TIMBRE DE PRENSA', 'TIMBRE DE PRENSA'), ('BOMBEROS', 'BOMBEROS'), ('TASA MUNICIPAL', 'TASA MUNICIPAL')], 'Tipo de Impuesto FEL', copy=False)
    codigo_unidad_gravable_fel = fields.Integer('Código Unidad Gravable FEL', copy=False)
