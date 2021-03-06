# -*- coding: utf-8 -*-

from json import dumps, loads, JSONEncoder, JSONDecoder

from openerp import models, fields, api, exceptions
from openerp.exceptions import ValidationError
from datetime import datetime, date
from dateutil.relativedelta import *
import json
import calendar
import logging



class Selection(models.Model):
    """Seed Selection"""
    _name = 'estate.nursery.selection'
    _description = "Seed Batch Selection"
    _inherit = ['mail.thread']


    def _default_session(self):
        return self.env['estate.nursery.batch'].browse(self._context.get('active_id'))

    name= fields.Char(store=True, track_visibility='onchange')
    selection_code=fields.Char("SFB",store=True)
    partner_id = fields.Many2one('res.partner')
    selectionline_ids = fields.One2many('estate.nursery.selectionline', 'selection_id', "Selection Lines",store=True)
    recoverytemp_ids = fields.One2many('estate.nursery.recoverytemp','selection_id')
    batch_id = fields.Many2one('estate.nursery.batch', "Batch",default=_default_session)
    stage_id = fields.Many2one('estate.nursery.stage',"Stage",store=True)
    batch_name = fields.Char('Batch Name',related='batch_id.name',store=True)
    age_seed = fields.Integer('Age Seed Batch',store=True)
    age_seed_calculate =fields.Integer("Seed Age",compute='_compute_age_seed',store=True)
    selectionstage_id = fields.Many2one('estate.nursery.selectionstage',"Selection Stage",track_visibility='onchange',
                                        required=True,
                                        store=True)

    qty_normal = fields.Integer("Normal Seed Quantity",compute="_compute_plannormal",store=True,track_visibility='onchange')
    qty_abnormal = fields.Integer("Abnormal Seed Quantity",store=True,compute='_compute_total',track_visibility='onchange')
    date_plant = fields.Date("Planted Date",required=False,store=True)
    qty_plant = fields.Integer("Planted Quantity",compute="_compute_plannormal",store=True)
    qty_plante = fields.Integer("Seed Planted Qty" , track_visibility='onchange',store=True)
    qty_recovery = fields.Integer("Quantity Recovery",compute="_compute_total_recovery",store=True)
    qty_recoveryabn = fields.Integer("Quantity Total Abnormal Selection and Recovery" ,
                                     digit=(2.2),compute='_compute_total_recovery_abnormal')
    qty_batch = fields.Integer("DO Quantity",required=False,readonly=True,related='batch_id.qty_received',store=True)

    selection_date = fields.Date("Selection Date",required=True,store=True)
    selec = fields.Integer(related='selectionstage_id.age_selection')
    comment = fields.Text("Additional Information")
    selectionline_count=fields.Integer("selection Cause",compute="_get_selectionline_count",store=True)
    nursery_information = fields.Selection([('0','untimely'),
                                            ('1','late'),('2','passed'),
                                            ('3','very late/Not recomend'),('4','very untimely')],
                                           default='0', string="Information Time" ,
                                           readonly=True,compute='_compute_dateinformation',store=True)

    nursery_lapseday = fields.Integer(string="Information Lapse of Day",
                                      required=False,readonly=True,compute='_compute_calculatedays',multi='sums',store=True)
    nursery_lapsemonth = fields.Integer(string="Information Lapse of Month",
                                        required=False,readonly=True,compute='_compute_calculatemonth',multi='sums',store=True)
    nursery_plandate = fields.Char('Planning Date',readonly=True,compute='_compute_calculateplandate')
    nursery_plandatemax = fields.Char('Planning Date max',readonly=True,compute="_compute_calculateplandatemax",visible=True)
    nursery_plandatemin = fields.Char('Planning Date min',readonly=True,compute="_compute_calculateplandatemin",visible=True)
    nursery_persentagen = fields.Float('Nursery Persentage Normal',digit=(2.2),compute='_compute_persentage',store=True)
    nursery_persentagea = fields.Float('Nursery Persentage Abnormal',digit=(2.2),compute='_compute_persentage',store=True)

    flag_recovery=fields.Boolean("is Recovery ?")
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('done', 'Done')], string="State",store=True)
    culling_location_id = fields.Many2one('estate.block.template',("Culling Location"),
                                          domain=[('estate_location', '=', True),
                                                  ('estate_location_level', '=', '3'),
                                                  ('estate_location_type', '=', 'nursery'),
                                                  ('scrap_location', '=', True)]
                                          ,related="batch_id.culling_location_id",store=True)
    location_type=fields.Many2one('stock.location',("location Last"),domain=[('name','=','Cleaving'),
                                                                             ('usage','=','inventory'),
                                                                             ],store=True,required=True,
                                  default=lambda self: self.location_type.search([('name','=','Cleaving')]))

    #sequence
    def create(self, cr, uid, vals, context=None):
        vals['selection_code']=self.pool.get('ir.sequence').get(cr, uid,'estate.nursery.selection')
        res=super(Selection, self).create(cr, uid, vals)
        return res

    #Search Selection Stage ID
    def search_selectionstage(self, cr, uid, args, offset=0, limit=None, order=None, context=None, count=False):
        if context is None:
            context = {}
        if context.get('search_default_filter_selection'):
            args.append((('selectionstage_id', 'child_of', context['search_default_filter_selection'])))
        return super(Selection, self).search(cr, uid, args, offset=offset, limit=limit, order=order, context=context, count=count)


    #workflow state
    @api.multi
    def action_draft(self):
        """Set Selection State to Draft."""
        self.ensure_one()
        self.write({'qty_normal': self.qty_normal})
        self.state = 'draft'

    @api.multi
    def action_confirmed(self):
        """Set Selection state to Confirmed."""
        self.ensure_one()
        self.state = 'confirmed'

    @api.multi
    def action_approved(self):
        """Approved Selection is planted Seed."""
        self.ensure_one()
        stage = self.selectionstage_id.name
        batch = self.batch_id.name
        self.write({'name':"Selection %s for %s" %(stage,batch)})
        self.action_receive()
        self.state = 'done'


    @api.multi
    def action_receive(self):
        self.ensure_one()
        normal = self.qty_normal
        abnormal = self.qty_abnormal
        selectionlineids = self.selectionline_ids
        if self.selectionline_ids:
            for item in selectionlineids:
                abnormal += item.qty
        self.write({'qty_abnormal': self.qty_abnormal})
        self.action_move()
        return True

    @api.multi
    def action_move(self):
        self.ensure_one()
        location_ids = set()
        for item in self.selectionline_ids:
            if item.location_id and item.qty > 0: # todo do not include empty quantity location
                location_ids.add(item.location_id.inherit_location_id)

        for location in location_ids:
            qty_total_abnormal = 0
            qty = self.env['estate.nursery.selectionline'].search([('location_id.inherit_location_id', '=', location.id),
                                                                   ('selection_id', '=', self.id)
                                                                   ])
            for i in qty:
                qty_total_abnormal += i.qty

            move_data = {
                'product_id': self.batch_id.product_id.id,
                'product_uom_qty': qty_total_abnormal,
                'origin':self.batch_id.name,
                'product_uom': self.batch_id.product_id.uom_id.id,
                'name': 'Selection Abnormal %s: %s'%(self.selectionstage_id.name,self.batch_id.name),
                'date_expected': self.nursery_plandate,
                'location_id': location.id,
                'location_dest_id': self.culling_location_id.inherit_location_id.id,
                'state': 'confirmed', # set to done if no approval required
                'restrict_lot_id': self.batch_id.lot_id.id # required by check tracking product
            }

            move = self.env['stock.move'].create(move_data)
            move.action_confirm()
            move.action_done()

        recovery_ids = set()
        for item in self.recoverytemp_ids:
            if item.location_id and item.qty_abn_recovery > 0: # todo do not include empty quantity location
                recovery_ids.add(item.location_id.inherit_location_id)

        for location in recovery_ids:
            qty_total_abnormal_recovery = 0
            qty = self.env['estate.nursery.recoverytemp'].search([('location_id.inherit_location_id', '=', location.id),
                                                                   ('selection_id', '=', self.id)
                                                                   ])
            for i in qty:
                qty_total_abnormal_recovery += i.qty_abn_recovery

            move_data = {
                'product_id': self.batch_id.product_id.id,
                'product_uom_qty': qty_total_abnormal_recovery,
                'product_uom': self.batch_id.product_id.uom_id.id,
                'origin':self.batch_id.name,
                'name': 'Selection Abnormal Recovery %s: %s'%(self.selectionstage_id.name,
                                                               self.batch_id.name),
                'date_expected': self.nursery_plandate,
                'location_id': location.id,
                'location_dest_id': self.location_type.id,
                'state': 'confirmed', # set to done if no approval required
                'restrict_lot_id': self.batch_id.lot_id.id # required by check tracking product
            }

            move = self.env['stock.move'].create(move_data)
            move.action_confirm()
            move.action_done()

    #compute function
    #compute qtyplant :
    @api.one
    @api.depends('qty_plant','qty_abnormal','flag_recovery','qty_plante','selectionline_ids','recoverytemp_ids','qty_recoveryabn')
    def _compute_plannormal(self):
        # self.ensure_one()
        plante = int(self.qty_plante)
        if self.flag_recovery == True:
            if self.selectionline_ids and self.recoverytemp_ids:
                self.qty_normal = plante - self.qty_recoveryabn
                self.qty_plant = plante - self.qty_recoveryabn
            elif self.recoverytemp_ids:
                self.qty_normal = plante - self.qty_recoveryabn
                self.qty_plant = plante - self.qty_recoveryabn
            else:
                self.qty_normal = plante
                self.qty_plant = plante
        if self.flag_recovery == False:
            if self.selectionline_ids :
                self.qty_normal = plante - self.qty_abnormal
                self.qty_plant = plante - self.qty_abnormal
            else :
                self.qty_normal = plante
                self.qty_plant = plante


    #compute abnormal and recovery :
    @api.one
    @api.depends('qty_recovery','qty_abnormal','qty_recoveryabn')
    def _compute_total_recovery_abnormal(self):
        # self.ensure_one()
        self.qty_recoveryabn = 0
        if self.qty_abnormal and self.qty_recovery:
            self.qty_recoveryabn = self.qty_abnormal + self.qty_recovery
        elif self.qty_recovery:
            self.qty_recoveryabn = self.qty_recovery
        elif self.qty_abnormal:
            self.qty_recoveryabn = self.qty_abnormal

    #selection count
    @api.depends('selectionline_ids')
    def _get_selectionline_count(self):
        for r in self:
            r.selectionline_count = len(r.selectionline_ids)

    # compute selectionLine
    @api.one
    @api.depends('selectionline_ids')
    def _compute_total(self):
        # self.ensure_one()
        self.qty_abnormal = 0
        if self.selectionline_ids:
            for item in self.selectionline_ids:
                self.qty_abnormal += item.qty
        return True

    #compute recoveryLine
    @api.one
    @api.depends('recoverytemp_ids')
    def _compute_total_recovery(self):
        # self.ensure_one()
        self.qty_recovery = 0
        if self.recoverytemp_ids:
            for item in self.recoverytemp_ids:
                self.qty_recovery += item.qty_abn_recovery
        return True

    #compute persentage
    @api.one
    @api.depends('qty_normal','qty_recoveryabn')
    def _compute_persentage(self):
        # self.ensure_one()
        total = self.qty_normal+self.qty_recoveryabn
        if total:
            self.nursery_persentagea =float(self.qty_recoveryabn)/float(total)*100.00
            self.nursery_persentagen =float(self.qty_normal)/float(total)*100.00

    #compute lapseday
    @api.multi
    @api.depends('date_plant','selection_date',)
    def _compute_calculatedays(self):
        self.ensure_one()
        res={}
        fmt = '%Y-%m-%d'
        if self.date_plant and self.selection_date :
            from_date = self.date_plant
            to_date = self.selection_date
            conv_fromdate = datetime.strptime(str(from_date), fmt)
            conv_todate = datetime.strptime(str(to_date),fmt)
            d1= conv_fromdate
            d2= conv_todate
            hasil= str((d2-d1).days)
            self.nursery_lapseday = hasil
        return res

    #compute lapse month
    @api.multi
    @api.depends('date_plant','selection_date')
    def _compute_calculatemonth(self):
        self.ensure_one()
        res={}
        fmt = '%Y-%m-%d'
        if self.date_plant and self.selection_date:
            from_date = self.date_plant
            to_date = self.selection_date
            conv_fromdate = datetime.strptime(str(from_date), fmt)
            conv_todate = datetime.strptime(str(to_date), fmt)
            d1 = conv_fromdate.month
            d2 = conv_todate.month
            rangeyear = conv_todate.year
            rangeyear1 = conv_fromdate.year
            rsult = rangeyear - rangeyear1
            yearresult = rsult * 12
            self.nursery_lapsemonth = (d2 + yearresult) - d1
        return res

    #compute planning date
    @api.multi
    @api.depends('date_plant','nursery_plandate','selec','selectionstage_id')
    def _compute_calculateplandate(self):
         self.ensure_one()
         fmt = '%Y-%m-%d'

         a = self.selec
         b = int(a)
         if self.selectionstage_id and self.date_plant :
             from_date = self.date_plant
             d1=datetime.strptime(str(from_date),fmt)
             date_after_month = datetime.date(d1)+ relativedelta(months=b)
             compute = date_after_month.strftime(fmt)
             self.nursery_plandate = compute
             # return True

    #compute planning max date
    @api.one
    @api.depends('date_plant','nursery_plandate','selectionstage_id')
    def _compute_calculateplandatemax(self):
         # self.ensure_one()
         fmt = '%Y-%m-%d'
         max = self.selectionstage_id.age_limit_max
         convmax = int(max)
         if self.date_plant and self.selectionstage_id:
             from_date = self.date_plant
             d1=datetime.strptime(str(from_date),fmt)
             date_after_month = datetime.date(d1)+ relativedelta(months=convmax)
             compute = date_after_month.strftime(fmt)
             self.nursery_plandatemax = compute
             return True

    #compute planning min date
    @api.one
    @api.depends('date_plant','nursery_plandate','selectionstage_id')
    def _compute_calculateplandatemin(self):
         # self.ensure_one()
         fmt = '%Y-%m-%d'
         min = self.selectionstage_id.age_limit_min
         convmin = int(min)
         if self.date_plant and self.selectionstage_id:
             from_date = self.date_plant
             d1=datetime.strptime(str(from_date),fmt)
             date_after_month = datetime.date(d1)+ relativedelta(months=convmin)
             compute = date_after_month.strftime(fmt)
             self.nursery_plandatemin = compute
             return True

    #information
    @api.one
    @api.depends('nursery_information','nursery_lapsemonth','nursery_plandate','selection_date',
                 'nursery_plandatemin','nursery_plandatemax')
    def _compute_dateinformation(self):
         # self.ensure_one()
         fmt = '%Y-%m-%d'

         if  self.selection_date:
             fromdt = self.selection_date
             plan = self.nursery_plandate
             planmax = self.nursery_plandatemax
             planmin = self.nursery_plandatemin
             pmax = planmax
             pmin = planmin
             planning=plan
             conv_fromdt = datetime.strptime(str(fromdt),fmt)
             conv_plan = datetime.strptime(str(planning),fmt)
             conv_planmax = datetime.strptime(str(pmax),fmt)
             conv_planmin = datetime.strptime(str(pmin),fmt)
             dmax = conv_planmax.month
             dmin = conv_planmin.month
             dmaxd = conv_planmax.day
             date_convfromdtM = conv_fromdt.month
             date_convplanM = conv_plan.month
             date_convfromdtD = conv_fromdt.day
             date_convplanD = conv_plan.day

             for c in range(1,8):
                 dateplanmax = date_convplanD + c
                 dateplanmin = date_convplanD - c

             #calculate range date
             if conv_fromdt and conv_plan and conv_planmax and conv_planmin:
                if date_convfromdtM == date_convplanM:
                    if date_convfromdtD == date_convplanD :
                        self.nursery_information = '2'#pass
                    elif  dateplanmax >= date_convfromdtD and date_convfromdtD >= dateplanmin:
                        self.nursery_information='2'
                    elif dateplanmax <= date_convfromdtD:
                        self.nursery_information='1' #late
                    else:
                        self.nursery_information='0'# untimely
                elif conv_fromdt > conv_planmax:
                    if date_convfromdtM >=dmax:
                        self.nursery_information = '3'#very late
                elif conv_fromdt < conv_planmin :
                     if date_convfromdtM > dmin:
                         self.nursery_information ='1'
                     elif date_convfromdtM <= dmin :
                         self.nursery_information = '4'# very untimely
                # return True

    #Computed age seed
    @api.one
    @api.depends('age_seed','date_plant','selection_date','age_seed_calculate')
    def _compute_age_seed(self):
        # self.ensure_one()
        res={}
        fmt = '%Y-%m-%d'
        if self.age_seed and self.selection_date:
            from_date = self.date_plant
            age_seed = self.age_seed
            to_date = self.selection_date
            conv_fromdate = datetime.strptime(str(from_date), fmt)
            conv_todate = datetime.strptime(str(to_date), fmt)
            d1 = conv_fromdate.month
            d2 = conv_todate.month
            rangeyear = conv_todate.year
            rangeyear1 = conv_fromdate.year
            rsult = rangeyear - rangeyear1
            yearresult = rsult * 12
            self.age_seed_calculate =((d2 + yearresult) - d1)-int(age_seed)
        return res


    #Onchange Stage id
    @api.multi
    @api.onchange('stage_id','selectionstage_id','selectionline_ids')
    def _changestage_id(self):
        self.ensure_one()
        if self.selectionstage_id:
            self.stage_id=self.selectionstage_id.stage_id

    #todo change stage untuk setiap selection
    # #onchange Stage
    # @api.multi
    # @api.onchange('selectionstage_id')
    # def _onchange_batch_id(self):
    #     selectionstagelist = self.env['estate.nursery.selection'].search([('batch_id.id','=',self.batch_id.id)])
    #     if self:
    #         arrSelectionstagelist = []
    #         for a in selectionstagelist:
    #             arrSelectionstagelist.append(a.selectionstage_id.id)
    #         return {
    #             'domain': {'selectionstage_id': [('id','not in',arrSelectionstagelist)]}
    #         }

    # onchange qty Normal
    @api.one
    @api.onchange('qty_normal')
    def _onchange_normal(self):
        # self.ensure_one()
        if self.selectionline_ids or self.selectionline_ids and self.recoverytemp_ids:
            self.write({'qty_normal' : self.qty_normal})

    #constraint Date for selection and date planted
    @api.multi
    @api.constrains('selection_date','date_plant')
    def _check_date(self):
        for obj in self:
            start_date = obj.date_plant
            end_date = obj.selection_date

            if start_date and end_date:
                DATETIME_FORMAT = "%Y-%m-%d"  ## Set your date format here
                from_dt = datetime.strptime(start_date, DATETIME_FORMAT)
                to_dt = datetime.strptime(end_date, DATETIME_FORMAT)
                if to_dt < from_dt:
                     raise ValidationError("Selection Date Should be Greater than Planted Date!" )

    #constraint Quantity abnormal and plantedselection
    @api.multi
    @api.constrains('qty_abnormal','qty_plante')
    def _check_constraint_qty(self):

        for obj in self:
            qty_selection =obj.qty_abnormal
            qty_batch=obj.qty_plante

            if qty_selection and qty_batch:
                if qty_selection > qty_batch:
                    error_msg="Quantity Abnormal %s is set more than Quantity Planted %s " %(qty_selection,qty_batch)
                    raise exceptions.ValidationError(error_msg)


class SelectionStage(models.Model):
    _name = 'estate.nursery.selectionstage'

    name = fields.Char(string="Selection Stage")
    age_limit_max= fields.Integer(string="Age Max",required=True)
    age_limit_min= fields.Integer(string="Age Min",required=True)
    age_selection= fields.Integer(string="Age Selection",required=True)
    info = fields.Selection([('draft','Draft'),('0','Age selection not less than age limit min'),
                             ('1','Age selection not more than age limit max'),
                             ('2','passed'),("3","Age Limit min not less than 1"),
                             ("4","Age Limit min not more than 12")],
                            compute='_compute_calculateinfo', default='draft', string="Information" ,
                            readonly=True,required=False)
    comment = fields.Text(string="Description or command")
    stage_id = fields.Many2one('estate.nursery.stage',"Nursery Stage",required=True)

    #constraint Age Limit and age selection
    @api.multi
    @api.constrains("age_limit_max","age_limit_min","age_selection")
    def _check_limitmax(self):
        for obj in self:
            if self.age_limit_min and self.age_limit_max:
                if self.age_selection > self.age_limit_max:
                    raise ValidationError("Age selection not more than age limit max!" )
                elif self.age_selection < self.age_limit_min:
                    raise ValidationError("Age selection should be Greater Than Age limit min!" )

    #constraint Age Limit min max and age selection
    @api.multi
    @api.constrains("age_limit_max","age_limit_min","age_selection")
    def _check_limitmin(self):
        for obj in self:
            limitmin = 1
            if self.age_limit_max and self.age_limit_min:
                if self.age_limit_min < limitmin:
                    raise ValidationError("Age Limit min not less than 1!" )

    #Limit age
    @api.one
    @api.depends("age_limit_max","age_limit_min","age_selection","info",)
    def _compute_calculateinfo(self):
        # self.ensure_one()
        maxa =self.age_limit_max
        mina=self.age_limit_min
        limitmax = self.age_limit_max
        limitmin = 1
        limit=[1,2,3,4,5,6,7,8,9,10,11,12]
        for item in limit:
            self.age_limit_max = item
        if self.age_limit_max and self.age_limit_min :
            if maxa == limitmax:
                self.info = "2"
                if self.age_selection >= maxa:
                    self.info = "1"
                elif self.age_selection <= mina:
                    self.info = "0"
                else:
                    inf = "2"
            elif maxa >= limitmax:
                self.info="4"
            elif mina < limitmin:
                self.info="3"


class SelectionLine(models.Model):
    """Seed Selection Line"""
    _name = 'estate.nursery.selectionline'
    _inherit = ['mail.thread']

    def _default_session(self):
        return self.env['estate.nursery.batch'].browse(self._context.get('active_id'))

    name=fields.Char(related='selection_id.name')
    partner_id=fields.Many2one("res.partner")
    qty = fields.Integer("Quantity Abnormal",required=True,store=True)
    cause_id = fields.Many2one("estate.nursery.cause",string="Cause",required=True,track_visibility='onchange')
    selectionstage =fields.Char(related="selection_id.selectionstage_id.name" , store=True)
    batch_id=fields.Many2one('estate.nursery.batch',"Selection",readonly=True,invisible=True,default=_default_session)
    stage_a_id=fields.Many2one('estate.nursery.stage')
    selection_id = fields.Many2one('estate.nursery.selection',"Selection",readonly=True,invisible=True)
    location_id = fields.Many2one('estate.block.template', "Location",
                                    domain=[('estate_location', '=', True),
                                            ('estate_location_level', '=', '3'),
                                            ('estate_location_type', '=', 'nursery'),
                                            ('scrap_location', '=', False),
                                            ],
                                             help="Fill in location seed planted.",
                                             required=True,)
    comment = fields.Text("Description")

    #Domain cause with stage id in selection form
    @api.multi
    @api.onchange('stage_a_id','selection_id','cause_id','location_id','batch_id')
    def _change_domain_causeid(self):

        if self:
            self.stage_a_id=self.selection_id.stage_id
            arrTransferSeed = []
            if self.stage_a_id.code == 'PN':
                batchTransferPn =self.env['estate.nursery.batchline'].search([('batch_id.id','=',self.batch_id.id),('location_id.id','!=',False)])
                for a in batchTransferPn:
                    arrTransferSeed.append(a.location_id.id)
            elif self.stage_a_id.code == 'MN':
                batchTransferMn = self.env['estate.nursery.transfermn'].search([('batch_id.id','=',self.batch_id.id)])
                for b in batchTransferMn:
                    stockLocation = self.env['estate.block.template'].search([('id','=',b.location_mn_id[0].id)])
                    stock= self.env['stock.location'].search([('id','=',stockLocation.inherit_location_id[0].id)])
                    idlot= self.env['estate.nursery.batch'].search([('id','=',self.batch_id.id)])
                    qty = self.env['stock.quant'].search([('lot_id.id','=',idlot[0].lot_id.id),('location_id.id','=',stock[0].id)])
                    if qty[0].qty > 0:
                        arrTransferSeed.append(b.location_mn_id.id)
            return {
                'domain': {'cause_id': [('stage_id.id', '=',self.stage_a_id.id)],
                           'location_id': [('id','in',arrTransferSeed)]},
            }
        return True


class Cause(models.Model):
    """Selection Cause (normal, afkir, etc)."""
    _name = 'estate.nursery.cause'

    name = fields.Char('Name')
    comment = fields.Text('Cause Description')
    code = fields.Char('Cause Abbreviation', size=3)
    sequence = fields.Integer('Sequence No')
    index=fields.Integer(compute='_compute_index')
    stage_id = fields.Many2one('estate.nursery.stage', "Nursery Stage",store=True)

    #create sequence
    @api.one
    def _compute_index(self):
        cr, uid, ctx = self.env.args
        self.index = self._model.search_count(cr, uid, [
            ('sequence', '<', self.sequence)
        ], context=ctx) + 1


class TempRecovery(models.Model):

    _name ="estate.nursery.recoverytemp"

    name=fields.Char(related="selection_id.name")
    qty_abn_recovery=fields.Integer("Abnormal Recovery",required=True)
    selection_id = fields.Many2one('estate.nursery.selection',"Selection",readonly=True,invisible=True)
    stage_a_id=fields.Many2one('estate.nursery.stage')
    location_id = fields.Many2one('estate.block.template', "Bedengan",
                                    domain=[('estate_location', '=', True),
                                            ('estate_location_level', '=', '3'),
                                            ('estate_location_type', '=', 'nursery'),
                                            ('scrap_location', '=', False),
                                            ],
                                             help="Fill in location seed planted.",
                                             required=True,)
    comment = fields.Text("Description")


    #Domain cause with stage id in selection form
    @api.multi
    @api.onchange('stage_a_id','selection_id','location_id')
    def _change_domain_locationid(self):
        # causestage = self.env['estate.nursery.cause'].browse([('stage_id.id', '=', self.stage_a_id.id)])

        if self:
            self.stage_a_id=self.selection_id.stage_id
            arrRecoverySeed = []
            if self.stage_a_id.code == 'PN':
                batchTransferPn =self.env['estate.nursery.batchline'].search([('batch_id.id','=',self.selection_id.batch_id.id),
                                                                              ('location_id.id','!=',False)])
                for a in batchTransferPn:
                    arrRecoverySeed.append(a.location_id.id)
            elif self.stage_a_id.code == 'MN':
                batchTransferMn = self.env['estate.nursery.transfermn'].search([('batch_id.id','=',self.selection_id.batch_id.id)])
                for b in batchTransferMn:
                    stockLocation = self.env['estate.block.template'].search([('id','=',b.location_mn_id[0].id)])
                    stock= self.env['stock.location'].search([('id','=',stockLocation.inherit_location_id[0].id)])
                    idlot= self.env['estate.nursery.batch'].search([('id','=',self.selection_id.batch_id.id)])
                    qty = self.env['stock.quant'].search([('lot_id.id','=',idlot[0].lot_id.id),('location_id.id','=',stock[0].id)])
                    if qty[0].qty > 0:
                        arrRecoverySeed.append(b.location_mn_id.id)
            return {
                'domain': {'location_id': [('id','in',arrRecoverySeed)]},
            }
        return True


