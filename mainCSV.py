from Bio import Entrez
from dotenv import load_dotenv
import os
from langchain_openai import AzureChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from neo4j import GraphDatabase
import requests
import re
import json
import csv

#set entrez email
Entrez.email=""
def welcome():
  print("Welcome to Paper to Neo4j")
  
  
def load_model():
  load_dotenv("llm.env")
  llm = AzureChatOpenAI(
		deployment_name = os.getenv("DEPLOYMENT"),
		openai_api_version = os.getenv("API_VERSION"),
		openai_api_key = os.getenv("API_KEY"),
		azure_endpoint = os.getenv("ENDPOINT"),
		openai_organization = os.getenv("ORGANIZATION"),
	)
  print("Model Loaded \n")
  return llm

def load_langchain():
  load_dotenv("langchain.env")
  os.environ["LANGCHAIN_TRACING_V2"] = os.getenv("LANGCHAIN_TRACING")
  os.environ["LANGCHAIN_API_KEY"] = os.getenv("LANGCHAIN_API_KEY")
  os.environ["LANGCHAIN_ENDPOINT"] = os.getenv("LANGCHAIN_ENDPOINT")
  print("Langchain Loaded \n")
  
def convert_pmid_to_pmcid(pmid):
  url = f"https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/?ids={pmid}&format=json"
  response = requests.get(url)
  data = response.json()
  if "records" in data and data["records"]:
    return data["records"][0].get("pmcid", None)
  return None

def fetch_full_text_pmcid(pmcid):
  handle = Entrez.efetch(db="pmc", id=pmcid, rettype="full", retmode="xml")
  response = handle.read()
  handle.close()
  full_text = response.decode("utf-8")
  output_file = os.path.join("raw_xml", f"{pmcid}.txt")
  with open(output_file, "w", encoding="utf-8") as file:
    file.write(full_text)
  try:
    cleaned = re.sub(r"<xml.*?</xml>|<xref.*?/xref>", "", full_text)
    #if (cleaned): print("clean")
    meta = re.search(r'(<!DOCTYPE.*?<abstract.*?>)', full_text, re.DOTALL)
    #if (meta): print("meta")
    abstract = re.search(r"<abstract.*?>.*?</abstract>", full_text, re.DOTALL)
    #if (abstract): print("abstract")
    full_text = re.search(r"</abstract>.*?<ref-list.*?>", cleaned, re.DOTALL)
    #if (full_text): print("full-text")
    references = re.search(r"<ref-list.*?>.*?</ref-list>", cleaned, re.DOTALL)
    full_text_clean = re.sub(r"<[^>]+>", "", full_text.group(0))
    full_text_clean = re.sub(r"\s+", " ", full_text_clean).strip()
    return meta.group(0), abstract.group(0), full_text_clean
  except Exception as e:
    print(e)
    return None, None, None


def create_full_text_json(text):
  json_generate = ChatPromptTemplate.from_messages([
        ("system", """
      You are a helpful assistant that extracts information from a PubMed article and formats it as JSON. Your task is to only produce a JSON from a vaccine design article.
      

      - Crate a JSON with the following keys:
						"vaccine_name": The specific name of the vaccine as given in the paper (ensure this is unique and not just a generic description).
						"vaccine_target_pathogen": the specific pathogen the vaccine is designed to target
						"vaccine_target_host": The host the vaccine is designed to be in
						"vaccine_model_host": The host the accine is experimented in
						"vaccine_delivery_method": The method of vaccine delivery (e.g., "intravenous").
						"vaccine_manufacturer": The manufacturer of the vaccine.
						"vaccine_storage_method": How the vaccine is stored.
          	"vaccine_stage": Must be one of the following: "research", "clinical", or "licensed".
						"vaccine_license": The license information if the vaccine stage is "licensed"; otherwise, this should be an empty string.
						"vaccine_antigen": The antigen that the vaccine uses
						"vaccine_formulation": The vaccine design, specific on the proteins
      
      Additional Instructions:
      - If a required piece of information cannot be directly found in the article, assign an empty string ("") to that key.
      - Ensure that the output is valid JSON.
      - **Clarity on Unimportant Vaccine Entries:** If the vaccine information is only generic (for example, if the vaccine name is merely "multi-epitope mRNA vaccine" without any additional details that make it unique), consider that information unimportant and do not output a Vaccine JSON object.

         """),
         ("human", "The PubMed article to convert to json is: {text}")])
  
  llm_chain = json_generate | llm
  generated_json = llm_chain.invoke({"text": text})
  return generated_json

def merge_json(json, csv_name):
  with open(csv_name, 'a', newline="", encoding="utf-8") as file:
    fieldnames = ["pmcid", "vaccine_name", "vaccine_target_pathogen", "vaccine_target_host", "vaccine_model_host", "vaccine_delivery_method", "vaccine_manufacturer", 
                  "vaccine_storage_method", "vaccine_stage", "vaccine_license", "vaccine_antigen", "vaccine_formulation"]
    write = csv.DictWriter(file, fieldnames=fieldnames)
    if not file:
      write.writeheader()
    write.writerow(json)
    
    
    
    

def main():
  welcome()
  
  global llm
  llm = load_model()
  load_langchain()
  csv_name = input("Enter a csv in data folder\n")
  csv_name = f"data/{csv_name}"
  while True:
    pmid = input("Enter pmid\n")
    pmcid = convert_pmid_to_pmcid(pmid)
    file_name = f"{pmcid}.txt"  
    existing_files = os.listdir("./raw_xml")
    if pmcid is not None and file_name not in existing_files:
      meta, abstract, full_text = fetch_full_text_pmcid(pmcid)
      if full_text is None:
        print("Bad Retrieval")
        continue
      full_text_json = create_full_text_json(full_text)
      print(full_text_json.content)
      json_blocks = re.findall(r"```json(.*?)```", full_text_json.content, re.DOTALL)
      paper_json_data = json.loads(re.sub(r"```json|```", "", json_blocks[0]))
      paper_json_data["pmcid"] = pmcid
      print(paper_json_data)
      merge_json(paper_json_data, csv_name)
    else:
      print("Failed to generate pmcid\n")




if __name__ == "__main__":
  main()