import java.io.*;
import java.nio.file.*;
import java.util.*;
import org.apache.poi.hssf.usermodel.*;
import org.apache.poi.hssf.eventusermodel.*;
import org.apache.poi.hssf.record.UnknownRecord;
import org.apache.poi.hssf.record.SupBookRecord;
import org.apache.poi.poifs.filesystem.*;
import org.apache.poi.hpsf.*;
import org.apache.poi.ss.usermodel.*;
import org.apache.poi.ss.util.*;

/** Passive BIFF8 reader. Never creates a FormulaEvaluator, resolves links or writes a workbook. */
public final class XlsReader {
 static Map<String,Object> obj(Object... pairs){Map<String,Object> m=new LinkedHashMap<>();for(int i=0;i<pairs.length;i+=2)m.put((String)pairs[i],pairs[i+1]);return m;}
 static String json(Object x){
  if(x==null)return "null";if(x instanceof Map<?,?>){List<String>a=new ArrayList<>();((Map<?,?>)x).forEach((k,v)->a.add(json(k.toString())+":"+json(v)));return "{"+String.join(",",a)+"}";}
  if(x instanceof Iterable<?>){List<String>a=new ArrayList<>();for(Object v:(Iterable<?>)x)a.add(json(v));return "["+String.join(",",a)+"]";}
  if(x instanceof Number){double v=((Number)x).doubleValue();return Double.isFinite(v)?x.toString():json(obj("type","special_float","value",x.toString()));}
  if(x instanceof Boolean)return x.toString();StringBuilder b=new StringBuilder("\"");for(char c:x.toString().toCharArray()){switch(c){case '"':b.append("\\\"");break;case '\\':b.append("\\\\");break;case '\n':b.append("\\n");break;case '\r':b.append("\\r");break;case '\t':b.append("\\t");break;default:if(c<32)b.append(String.format("\\u%04x",(int)c));else b.append(c);}}return b.append('"').toString();
 }
 static void emit(Map<String,Object> locator,Object content,List<String> limits){Map<String,Object> row=obj("locator",locator,"text",json(content),"extent","original_biff8_cells_formulas_structure");if(!limits.isEmpty()){row.put("unhandled_visuals",true);row.put("reading_limits",new ArrayList<>(limits));}System.out.println(json(row));}
 static int u16(byte[]b,int p){return (b[p]&255)|((b[p+1]&255)<<8);}
 static long u32(byte[]b,int p){return Integer.toUnsignedLong(u16(b,p)|(u16(b,p+2)<<16));}
 static String hex(byte[]b,int p,int n){return HexFormat.of().formatHex(b,p,p+n);}
 static void streams(DirectoryEntry d,String prefix,List<String> out){for(Entry e:d){String p=prefix+e.getName();if(e.isDirectoryEntry())streams((DirectoryEntry)e,p+"/",out);else out.add(p);}}
 static Object value(HSSFCell c,CellType type){switch(type){case NUMERIC:return c.getNumericCellValue();case STRING:return c.getStringCellValue();case BOOLEAN:return c.getBooleanCellValue();case ERROR:return obj("error_code",c.getErrorCellValue()&255,"error",FormulaError.forInt(c.getErrorCellValue()).getString());case BLANK:return null;default:throw new IllegalArgumentException("unhandled_cell_type:"+type);}}
 static Map<String,Object> style(HSSFCellStyle s,HSSFWorkbook w){HSSFFont f=w.getFontAt(s.getFontIndex());return obj("index",s.getIndex(),"number_format",s.getDataFormatString(),"alignment",s.getAlignment().name(),"vertical_alignment",s.getVerticalAlignment().name(),"wrap",s.getWrapText(),"rotation",s.getRotation(),"indent",s.getIndention(),"locked",s.getLocked(),"hidden_formula",s.getHidden(),"fill",s.getFillPattern().name(),"fill_foreground_palette_index",s.getFillForegroundColor(),"fill_background_palette_index",s.getFillBackgroundColor(),"borders",List.of(s.getBorderTop().name(),s.getBorderRight().name(),s.getBorderBottom().name(),s.getBorderLeft().name()),"font",obj("name",f.getFontName(),"height",f.getFontHeight(),"bold",f.getBold(),"italic",f.getItalic(),"underline",f.getUnderline(),"strikeout",f.getStrikeout(),"palette_index",f.getColor()));}
 public static void main(String[]args) throws Exception {
  if(args.length!=1)throw new IllegalArgumentException("one_read_only_source_required");
  try(POIFSFileSystem fs=new POIFSFileSystem(new File(args[0]),true)){
   DirectoryNode root=fs.getRoot();String workbookStream=root.hasEntry("Workbook")?"Workbook":"Book";byte[] b;try(DocumentInputStream in=root.createDocumentInputStream(workbookStream)){b=in.readAllBytes();}
   if(b.length<8||u16(b,0)!=0x0809||u16(b,4)!=0x0600)throw new IOException("historic_biff_requires_separate_decoder");
   List<String> limits=new ArrayList<>(),streams=new ArrayList<>();streams(root,"",streams);
   for(String s:streams)if(!Set.of(workbookStream,"\u0005SummaryInformation","\u0005DocumentSummaryInformation").contains(s))limits.add("uninterpreted_ole_stream:"+s);
   Map<Integer,Map<String,String>> rawFormulas=new HashMap<>();List<Map<String,Object>> groupRecords=new ArrayList<>();Map<Integer,Integer> sheetOffsets=new HashMap<>();int sheetNo=-1,boundNo=0;Map<String,Integer> inventory=new TreeMap<>();
   for(int p=0;p<b.length;){
    if(p+4>b.length)throw new IOException("truncated_biff_header");int id=u16(b,p),len=u16(b,p+2),d=p+4;if(d+len>b.length)throw new IOException("truncated_biff_record");
    if(id==0&&len==0)break;
    inventory.merge(String.format("0x%04x",id),1,Integer::sum);
    if(id==0x0085){sheetOffsets.put((int)u32(b,d),boundNo++);if(len>5&&b[d+5]!=0)limits.add("unsupported_sheet_type:"+(b[d+5]&255));}
    if(sheetOffsets.containsKey(p))sheetNo=sheetOffsets.get(p);
    if(id==0x0006){if(len<22)throw new IOException("truncated_formula");int n=u16(b,d+20);if(n>len-22)throw new IOException("truncated_formula_tokens");rawFormulas.computeIfAbsent(sheetNo,k->new HashMap<>()).put(u16(b,d)+":"+u16(b,d+2),hex(b,d,len));}
    if(id==0x04bc||id==0x0221)groupRecords.add(obj("sheet_index",sheetNo,"record_id",String.format("0x%04x",id),"original_record_hex",hex(b,d,len)));
    if(id==0x0236)limits.add("uninterpreted_data_table_formula");
    p=d+len;
   }
   HSSFRequest request=new HSSFRequest();Set<String> unknown=new TreeSet<>();request.addListenerForAllRecords(r->{String name=r.getClass().getName();if(r instanceof UnknownRecord||name.contains(".chart.")||name.contains(".pivottable."))unknown.add(name+":"+Integer.toHexString(r.getSid()&65535));if(r instanceof SupBookRecord&&((SupBookRecord)r).isExternalReferences())unknown.add("external_workbook_dependency_not_opened");});new HSSFEventFactory().processWorkbookEvents(request,fs);for(String s:unknown)limits.add("uninterpreted_biff_record:"+s);
   for(String propertyStream:List.of("\u0005SummaryInformation","\u0005DocumentSummaryInformation"))if(root.hasEntry(propertyStream)){
    List<Object> sections=new ArrayList<>();List<String> pl=new ArrayList<>();
    try(DocumentInputStream pin=root.createDocumentInputStream(propertyStream)){
     PropertySet props=PropertySetFactory.create(pin);for(Section section:props.getSections()){List<Object> properties=new ArrayList<>();for(Property prop:section.getProperties()){Object val=prop.getValue();if(val instanceof byte[]){val=obj("binary_base64",Base64.getEncoder().encodeToString((byte[])val));pl.add("opaque_document_property:"+prop.getID());}if(val instanceof java.util.Date)val=((java.util.Date)val).toInstant().toString();properties.add(obj("id",prop.getID(),"variant_type",prop.getType(),"value",val));}sections.add(obj("format_id",section.getFormatID().toString(),"properties",properties));}
    }catch(Exception e){pl.add("document_properties_decode_failed:"+e.getClass().getSimpleName());}
    emit(obj("kind","document_properties","stream",propertyStream),sections,pl);
   }
   try(HSSFWorkbook w=new HSSFWorkbook(fs,false)){
    List<Object> names=new ArrayList<>();for(HSSFName n:w.getAllNames()){try{names.add(obj("name",n.getNameName(),"sheet_index",n.getSheetIndex(),"formula",n.getRefersToFormula(),"comment",n.getComment(),"is_function",n.isFunctionName()));}catch(RuntimeException e){names.add(obj("name",n.getNameName(),"decode_error",e.getClass().getSimpleName()));limits.add("name_formula_decode_failed:"+n.getNameName());}}
    List<Object> styles=new ArrayList<>();for(int i=0;i<w.getNumCellStyles();i++)styles.add(style(w.getCellStyleAt(i),w));
    List<Object> palette=new ArrayList<>();for(int i=0;i<64;i++){var col=w.getCustomPalette().getColor(i);if(col!=null){short[]rgb=col.getTriplet();palette.add(obj("index",i,"rgb",List.of(rgb[0],rgb[1],rgb[2])));}}
    emit(obj("kind","workbook_metadata"),obj("decoder","Apache POI 5.5.1","source_format","BIFF8","date_system",w.getInternalWorkbook().isUsing1904DateWindowing()?"1904":"1900","names",names,"styles",styles,"palette",palette,"ole_streams",streams,"biff_record_counts",inventory,"formula_group_original_records",groupRecords,"formula_semantics","Formula text is decoded from original BIFF tokens, not evaluated. Cached values are the original stored results; they may be stale. Hidden data are included. Empty missing cells are distinct from explicit blanks. Merged ranges have one upper-left anchor, not separate blank observations.","executed_macros",false,"evaluated_formulas",false,"followed_external_links",false),limits);
    int seenFormulas=0;
    for(int i=0;i<w.getNumberOfSheets();i++){
     HSSFSheet sheet=w.getSheetAt(i);List<String> sl=new ArrayList<>();List<Object> merges=new ArrayList<>();for(CellRangeAddress m:sheet.getMergedRegions())merges.add(obj("range",m.formatAsString(),"anchor",new CellReference(m.getFirstRow(),m.getFirstColumn()).formatAsString()));
     List<Object> columns=new ArrayList<>();for(int c=0;c<256;c++)if(sheet.isColumnHidden(c)||sheet.getColumnWidth(c)!=sheet.getDefaultColumnWidth()*256||sheet.getColumnStyle(c)!=null)columns.add(obj("column",CellReference.convertNumToColString(c),"hidden",sheet.isColumnHidden(c),"width",sheet.getColumnWidth(c),"style_index",sheet.getColumnStyle(c)==null?null:sheet.getColumnStyle(c).getIndex()));
     List<Object> comments=new ArrayList<>();HSSFPatriarch drawing=sheet.getDrawingPatriarch();if(drawing!=null)for(HSSFShape shape:drawing.getChildren()){if(shape instanceof HSSFComment){HSSFComment co=(HSSFComment)shape;comments.add(obj("coordinate",new CellReference(co.getRow(),co.getColumn()).formatAsString(),"text",co.getString().getString(),"author",co.getAuthor(),"visible",co.isVisible()));}else sl.add("uninterpreted_drawing:"+shape.getClass().getSimpleName());}
     if(sheet.getSheetConditionalFormatting().getNumConditionalFormattings()>0)sl.add("uninterpreted_conditional_formatting");if(!sheet.getDataValidations().isEmpty())sl.add("uninterpreted_data_validation");
     emit(obj("sheet",sheet.getSheetName(),"sheet_state",w.getSheetVisibility(i).name().toLowerCase(),"kind","sheet_geometry"),obj("merged_ranges",merges,"columns",columns,"comments",comments,"default_row_height",sheet.getDefaultRowHeight(),"default_column_width",sheet.getDefaultColumnWidth(),"header",obj("left",sheet.getHeader().getLeft(),"center",sheet.getHeader().getCenter(),"right",sheet.getHeader().getRight()),"footer",obj("left",sheet.getFooter().getLeft(),"center",sheet.getFooter().getCenter(),"right",sheet.getFooter().getRight())),sl);
     List<Object> rows=new ArrayList<>();int start=0,end=0;
     for(Row rr:sheet){HSSFRow row=(HSSFRow)rr;if(rows.isEmpty())start=row.getRowNum()+1;end=row.getRowNum()+1;List<Object> cells=new ArrayList<>();List<String> rl=new ArrayList<>();
      for(Cell cc:row){HSSFCell c=(HSSFCell)cc;CellType type=c.getCellType();Map<String,Object> cell=obj("coordinate",c.getAddress().formatAsString(),"type",type.name().toLowerCase(),"style_index",c.getCellStyle().getIndex());
       if(type==CellType.FORMULA){seenFormulas++;CellType ct=c.getCachedFormulaResultType();cell.put("cached_type",ct.name().toLowerCase());cell.put("cached",value(c,ct));cell.put("original_formula_record_hex",rawFormulas.getOrDefault(i,Map.of()).get(c.getRowIndex()+":"+c.getColumnIndex()));if(cell.get("original_formula_record_hex")==null)rl.add("original_formula_record_not_matched:"+c.getAddress());try{cell.put("formula","="+c.getCellFormula());if(c.isPartOfArrayFormulaGroup())cell.put("array_range",c.getArrayFormulaRange().formatAsString());}catch(RuntimeException e){cell.put("formula_decode_error",e.getClass().getSimpleName());rl.add("formula_decode_failed:"+c.getAddress());}}
       else cell.put("value",value(c,type));
       HSSFComment comment=c.getCellComment();if(comment!=null)cell.put("comment",obj("author",comment.getAuthor(),"text",comment.getString().getString(),"visible",comment.isVisible()));HSSFHyperlink link=c.getHyperlink();if(link!=null)cell.put("hyperlink",obj("address",link.getAddress(),"label",link.getLabel(),"type",link.getType().name(),"followed",false));cells.add(cell);
      }
      rows.add(obj("row",row.getRowNum()+1,"hidden",row.getZeroHeight(),"height",row.getHeight(),"outline_level",row.getOutlineLevel(),"cells",cells));
      if(!rl.isEmpty()){emit(obj("sheet",sheet.getSheetName(),"kind","cell_reading_limits","row",row.getRowNum()+1),rl,rl);}
      if(rows.size()==100){emit(obj("sheet",sheet.getSheetName(),"sheet_state",w.getSheetVisibility(i).name().toLowerCase(),"row_start",start,"row_end",end),rows,List.of());rows=new ArrayList<>();}
     }
     if(!rows.isEmpty())emit(obj("sheet",sheet.getSheetName(),"sheet_state",w.getSheetVisibility(i).name().toLowerCase(),"row_start",start,"row_end",end),rows,List.of());
    }
    int rawCount=rawFormulas.values().stream().mapToInt(Map::size).sum();if(seenFormulas!=rawCount)emit(obj("kind","formula_inventory_mismatch"),obj("raw",rawCount,"decoded",seenFormulas),List.of("formula_inventory_mismatch"));
   }
  }
 }
}
